django-cities-light -- *Simple django-cities alternative*
=========================================================

This add-on provides models and commands to import country/city data into your database.
The data is pulled from [GeoNames](http://www.geonames.org/) and contains:

  - country names
  - optionnal city names

Spatial query support is not required by this application.

This application is very simple and is useful if you want to make a simple
address book for example. If you intend to build a fully featured spatial
database, you should use
[django-cities](https://github.com/coderholic/django-cities).

Installation
------------

Install django-cities-light (currently not working):

    pip install django-cities-light

Or the development version:

    pip install -e git+git@github.com:yourlabs/django-cities-light.git#egg=cities_light

Add `cities_light` to your `INSTALLED_APPS`.

The City model is optionnal. If you want to disable it, add setting:

    CITIES_LIGHT_ENABLE_CITY=False

Now, run syncdb, it will only create tables for models that are not disabled:

    ./manage.py syncdb

Data update
-----------

Finnaly, populate your database with command:

    ./manage.py cities_light

This command is well documented, consult the help with:
    
    ./manage.py help cities_light

Filtering data import
---------------------

An example is worth 1000 words: if you want to import only cities from France,
USA and Belgium you could do as such:

    import cities_light

    def filter_city_import(sender, items, **kwargs):
        if items[8] not in ('FR', 'US', 'BE'):
            raise cities_light.InvalidItems()

    cities_light.signals.city_items_pre_import.connect(filter_city_import)

Note: this signal gets a list rather than a City instance for performance reasons.

Configure logging
-----------------

This command is made to be compatible with background usage like from cron, to
keep the database fresh. So it doesn't do direct output. To get output from
this command, simply configure a handler and formatter for `cities_light`
logger. For example:

    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'simple': {
                'format': '%(levelname)s %(message)s'
            },
        },
        'handlers': {
            'console':{
                'level':'DEBUG',
                'class':'logging.StreamHandler',
                'formatter': 'simple'
            },
        },
        'loggers': {
            'cities_light': {
                'handlers':['console'],
                'propagate': True,
                'level':'DEBUG',
            },
            # also use this one to see SQL queries
            'django': {
                'handlers':['console'],
                'propagate': True,
                'level':'DEBUG',
            },
        }
    }

