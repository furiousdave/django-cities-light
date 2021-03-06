import os
import os.path
import logging
import optparse
import resource

try:
    import cPickle as pickle
except ImportError:
    import pickle

import progressbar

from django.core.management.base import BaseCommand
from django.utils.encoding import force_unicode

from ...exceptions import *
from ...signals import *
from ...models import *
from ...settings import *
from ...geonames import Geonames


class MemoryUsageWidget(progressbar.ProgressBarWidget):
    def update(self, pbar):
        return '%s kB' % resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


class Command(BaseCommand):
    args = '''
[--force-all] [--force-import-all \\]
                              [--force-import countries.txt cities.txt ...] \\
                              [--force countries.txt cities.txt ...]
    '''.strip()
    help = '''
Download all files in CITIES_LIGHT_COUNTRY_SOURCES if they were updated or if
--force-all option was used.
Import country data if they were downloaded or if --force-import-all was used.

Same goes for CITIES_LIGHT_CITY_SOURCES.

It is possible to force the download of some files which have not been updated
on the server:

    manage.py --force cities15000.txt countryInfo.txt

It is possible to force the import of files which weren't downloaded using the
--force-import option:

    manage.py --force-import cities15000.txt countryInfo.txt
    '''.strip()

    logger = logging.getLogger('cities_light')

    option_list = BaseCommand.option_list + (
        optparse.make_option('--force-import-all', action='store_true',
            default=False, help='Import even if files are up-to-date.'
        ),
        optparse.make_option('--force-all', action='store_true', default=False,
            help='Download and import if files are up-to-date.'
        ),
        optparse.make_option('--force-import', action='append', default=[],
            help='Import even if files matching files are up-to-date'
        ),
        optparse.make_option('--force', action='append', default=[],
            help='Download and import even if matching files are up-to-date'
        ),
        optparse.make_option('--noinsert', action='store_true',
            default=False,
            help='Update existing data only'
        ),
        optparse.make_option('--hack-translations', action='store_true',
            default=False,
            help='Set this if you intend to import translations a lot'
        ),
    )

    def handle(self, *args, **options):
        if not os.path.exists(DATA_DIR):
            self.logger.info('Creating %s' % DATA_DIR)
            os.mkdir(DATA_DIR)

        translation_hack_path = os.path.join(DATA_DIR, 'translation_hack')

        self.noinsert = options['noinsert']
        self.widgets = [
            'RAM used: ',
            MemoryUsageWidget(),
            ' ',
            progressbar.ETA(),
            ' Done: ',
            progressbar.Percentage(),
            progressbar.Bar(),
        ]

        for url in SOURCES:
            destination_file_name = url.split('/')[-1]

            force = options['force_all'] or \
                destination_file_name in options['force']

            geonames = Geonames(url, force=force)
            downloaded = geonames.downloaded

            force_import = options['force_import_all'] or \
                destination_file_name in options['force_import']

            if downloaded or force_import:
                self.logger.info('Importing %s' % destination_file_name)

                if url in TRANSLATION_SOURCES:
                    if options['hack_translations']:
                        if os.path.exists(translation_hack_path):
                            self.logger.debug(
                                'Using translation parsed data: %s' %
                                translation_hack_path)
                            continue

                i = 0
                progress = progressbar.ProgressBar(maxval=geonames.num_lines(),
                    widgets=self.widgets)

                for items in geonames.parse():
                    if url in CITY_SOURCES:
                        self.city_import(items)
                    elif url in REGION_SOURCES:
                        self.region_import(items)
                    elif url in COUNTRY_SOURCES:
                        self.country_import(items)
                    elif url in TRANSLATION_SOURCES:
                        self.translation_parse(items)

                    i += 1
                    progress.update(i)

                progress.finish()

                if url in TRANSLATION_SOURCES and options['hack_translations']:
                    with open(translation_hack_path, 'w+') as f:
                        pickle.dump(self.translation_data, f)

        if options['hack_translations']:
            with open(translation_hack_path, 'r') as f:
                self.translation_data = pickle.load(f)

        self.logger.info('Importing parsed translation in the database')
        self.translation_import()

    def _get_country(self, code2):
        '''
        Simple lazy identity map for code2->country
        '''
        if not hasattr(self, '_country_codes'):
            self._country_codes = {}

        if code2 not in self._country_codes.keys():
            self._country_codes[code2] = Country.objects.get(code2=code2)

        return self._country_codes[code2]

    def _get_region(self, country_code2, region_id):
        '''
        Simple lazy identity map for (country_code2, region_id)->region
        '''
        if not hasattr(self, '_region_codes'):
            self._region_codes = {}

        country = self._get_country(country_code2)
        if country.code2 not in self._region_codes:
            self._region_codes[country.code2] = {}

        if region_id not in self._region_codes[country.code2]:
            self._region_codes[country.code2][region_id] = Region.objects.get(
                country=country, geoname_code=region_id)

        return self._region_codes[country.code2][region_id]

    def country_import(self, items):
        try:
            country = Country.objects.get(code2=items[0])
        except Country.DoesNotExist:
            if self.noinsert:
                return
            country = Country(code2=items[0])

        country.name = force_unicode(items[4])
        country.code3 = items[1]
        country.continent = items[8]
        country.tld = items[9][1:]  # strip the leading dot
        if items[16]:
            country.geoname_id = items[16]
        country.save()

    def region_import(self, items):
        try:
            region_items_pre_import.send(sender=self, items=items)
        except InvalidItems:
            return

        code2, geoname_code = items[0].split('.')
        try:
            kwargs = dict(geoname_code=geoname_code,
                country=self._get_country(code2))
        except Country.DoesNotExist:
            if self.noinsert:
                return
            else:
                raise

        try:
            region = Region.objects.get(**kwargs)
        except Region.DoesNotExist:
            if self.noinsert:
                return
            region = Region(**kwargs)

        region.name = force_unicode(items[1])
        region.geoname_id = items[3]
        region.save()

    def city_import(self, items):
        try:
            city_items_pre_import.send(sender=self, items=items)
        except InvalidItems:
            return

        try:
            kwargs = dict(name=force_unicode(items[1]),
                country=self._get_country(items[8]))
        except Country.DoesNotExist:
            if self.noinsert:
                return
            else:
                raise

        try:
            city = City.objects.get(**kwargs)
        except City.DoesNotExist:
            if self.noinsert:
                return
            city = City(**kwargs)

        save = False
        if not city.region:
            city.region = self._get_region(items[8], items[10])
            save = True

        if not city.latitude:
            city.latitude = items[4]
            save = True

        if not city.longitude:
            city.longitude = items[5]
            save = True

        if not TRANSLATION_SOURCES and not city.alternate_names:
            city.alternate_names = force_unicode(items[3])
            save = True

        if not city.geoname_id:
            # city may have been added manually
            city.geoname_id = items[0]
            save = True

        if save:
            city.save()

    def translation_parse(self, items):
        if not hasattr(self, 'translation_data'):
            self.country_ids = Country.objects.values_list('geoname_id',
                flat=True)
            self.region_ids = Region.objects.values_list('geoname_id',
                flat=True)
            self.city_ids = City.objects.values_list('geoname_id', flat=True)
            self.translation_data = {
                Country: {},
                Region: {},
                City: {},
            }

        if len(items) > 4:
            # avoid shortnames, colloquial, and historic
            return

        if items[2] not in TRANSLATION_LANGUAGES:
            return

        # arg optimisation code kills me !!!
        items[1] = int(items[1])

        if items[1] in self.country_ids:
            model_class = Country
        elif items[1] in self.region_ids:
            model_class = Region
        elif items[1] in self.city_ids:
            model_class = City
        else:
            return

        if items[1] not in self.translation_data[model_class]:
            self.translation_data[model_class][items[1]] = {}

        if items[2] not in self.translation_data[model_class][items[1]]:
            self.translation_data[model_class][items[1]][items[2]] = []

        self.translation_data[model_class][items[1]][items[2]].append(items[3])

    def translation_import(self):
        data = getattr(self, 'translation_data', None)

        if not data:
            return

        max = 0
        for model_class, model_class_data in data.items():
            max += len(model_class_data.keys())

        i = 0
        progress = progressbar.ProgressBar(maxval=max, widgets=self.widgets)
        for model_class, model_class_data in data.items():
            for geoname_id, geoname_data in model_class_data.items():
                try:
                    model = model_class.objects.get(geoname_id=geoname_id)
                except model_class.DoesNotExist:
                    continue
                save = False

                if not model.alternate_names:
                    alternate_names = []
                else:
                    alternate_names = model.alternate_names.split(',')

                for lang, names in geoname_data.items():
                    if lang == 'post':
                        # we might want to save the postal codes somewhere
                        # here's where it will all start ...
                        continue

                    for name in names:
                        name = force_unicode(name)
                        if name == model.name:
                            continue

                        if name not in alternate_names:
                            alternate_names.append(name)

                alternate_names = u','.join(alternate_names)
                if model.alternate_names != alternate_names:
                    model.alternate_names = alternate_names
                    save = True

                if save:
                    model.save()

                i += 1
                progress.update(i)
