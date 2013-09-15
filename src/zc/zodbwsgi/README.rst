.. image:: https://travis-ci.org/zopefoundation/zc.zodbwsgi.png?branch=master
   :target: https://travis-ci.org/zopefoundation/zc.zodbwsgi

WSGI Middleware for Managing ZODB Database Connections
======================================================

The zc.zodbwsgi provides middleware for managing connections to a ZODB
database. It combines several features into a single middleware
component:

- database configuration
- database initialization
- connection management
- optional transaction management
- optional request retry on conflict errors (using repoze.retry)
- optionaly limiting the number of simultaneous database connections
- applications can take over connection and transaction management on
  a case-by-case basis, for example to support the occasional
  long-running request.

It is designed to work with paste deployment and provides a
"filter_app_factory" entry point, named "main".

A number of configuration options are provided. Option values are
strings.

configuration
   A required ZConfig formatted ZODB database configuration

   If multiple databases are defined, they will define a
   multi-database. Connections will be to the first defined database.

initializer
   An optional database initialization function of the form
   ``module:expression``

key
   An optional name of a WSGI environment key for database connections

   This defaults to "zodb.connection".

transaction_management
   An optional flag (either "true" or "false") indicating whether the
   middleware manages transactions.

   Transaction management is enabled by default.

transaction_key
   An optional name of a WSGI environment key for transaction managers

   This defaults to "transaction.manager". The key will only be
   present if transaction management is enabled.

thread_transaction_manager
   An option flag (either "true" or "false") indicating whether the
   middleware will use a thread-aware transaction mananger (e.g.,
   thread.TransactionManager).

   Using a thread-aware transaction mananger is convenient if you're
   using a server that always a request in the same thread, such as
   servers thaat use thread pools, or that create threads for each
   request.

   If you're using a server, such as gevent, that handles multiple
   requests in the same thread or a server that might handle the same
   request in different threads, then you should set this option to
   false.

   Defaults to True.

retry
   An optional retry count

   The default is "3", indicating that requests will be retried up to
   3 times.  Use "0" to disable retries.

   Note that when retry is not "0", request bodies will be buffered.

demostorage_manage_header
   An optional entry that controls whether the filter will support push/pop
   support for the underlying demostorage.

   If a value is provided, it'll check for that header in the request. If found
   and its value is "push" or "pop" it'll perform the relevant operation. The
   middleware will return a response indicating the action taken _without_
   processing the rest of the pipeline.

   Also note that this only works if the underlying storage is a DemoStorage.

max_connections
   Maximum number of simultaneous 

.. contents::

Basic usage
-----------

Let's look at some examples.

First we define an demonstration "application" that we can pass to our
factory::

    import transaction, ZODB.POSException
    from sys import stdout

    class demo_app:
        def __init__(self, default):
            pass
        def __call__(self, environ, start_response):
            start_response('200 OK', [('content-type', 'text/html')])
            root = environ['zodb.connection'].root()
            path = environ['PATH_INFO']
            if path == '/inc':
                root['x'] = root.get('x', 0) + 1
                if 'transaction.manager' in environ:
                    environ['transaction.manager'].get().note('path: %r' % path)
                else:
                    transaction.commit() # We have to commit our own!
            elif path == '/conflict':
                print >>stdout, 'Conflict!'
                raise ZODB.POSException.ConflictError
            elif path == "/tm":
                tm = environ["transaction.manager"]
                return ["thread tm: " + str(tm is transaction.manager)]
            return [repr(root)]

.. -> src

   >>> import zc.zodbwsgi.tests
   >>> exec(src, zc.zodbwsgi.tests.__dict__)

Now, we'll define our application factory using a paste deployment
configuration::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb>
        <demostorage>
        </demostorage>
      </zodb>

.. -> src

    >>> open('paste.ini', 'w').write(src)

Here, for demonstration purposes, we used an in-memory demo storage.

Now, we'll create an application with paste:

    >>> import paste.deploy, os
    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))

The resulting applications has a database attribute (mainly for
testing) with the created database.
Being newly initialized, the database is empty:

    >>> conn = app.database.open()
    >>> conn.root()
    {}

Let's do an "increment" request.

    >>> import webtest
    >>> testapp = webtest.TestApp(app)
    >>> testapp.get('/inc')
    <200 OK text/html body="{'x': 1}">

Now, if we look at the database, we see that there's now data in the
root object:

    >>> conn.sync()
    >>> conn.root()
    {'x': 1}

Database initialization
-----------------------

We can supply a database initialization function using the initializer
option.  Let's define an initialization function::

    import transaction

    def initialize_demo_db(db):
        conn = db.open()
        conn.root()['x'] = 100
        transaction.commit()
        conn.close()

.. -> src

   >>> exec(src, zc.zodbwsgi.tests.__dict__)

and update our paste configuration to use it::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb>
        <demostorage>
        </demostorage>
      </zodb>

   initializer = zc.zodbwsgi.tests:initialize_demo_db

.. -> src

    >>> open('paste.ini', 'w').write(src)

Now, when we use the application, we see the impact of the
initializer:

    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> testapp.get('/inc')
    <200 OK text/html body="{'x': 101}">

.. Our application updated transaction meta data when called under
   transaction control.

    >>> app.database.history(conn.root()._p_oid, 1)[0]['description']
    "path: '/inc'"

Disabling transaction management
--------------------------------

Sometimes, you may not want the middleware to control transactions.
You might do this if your application used multiple databases,
including non-ZODB databases [#multidb]_.  You can suppress
transaction management by supplying a value of "false" for the
transaction_management option::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb>
        <demostorage>
        </demostorage>
      </zodb>

   initializer = zc.zodbwsgi.tests:initialize_demo_db
   transaction_management = false

.. -> src

    >>> open('paste.ini', 'w').write(src)
    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> testapp.get('/inc')
    <200 OK text/html body="{'x': 101}">

    >>> app.database.history('\0'*8, 1)[0]['description']
    ''

Suppressing request retry
-------------------------

By default, zc.zodbwsgi adds ``repoze.retry`` middleware to retry requests
when there are conflict errors:

    >>> import ZODB.POSException
    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> try: testapp.get('/conflict')
    ... except ZODB.POSException.ConflictError: pass
    ... else: print 'oops'
    Conflict!
    Conflict!
    Conflict!
    Conflict!

Here we can see that the request was retried 3 times.

We can suppress this by supplying a value of "0" for the retry option::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb>
        <demostorage>
        </demostorage>
      </zodb>

   retry = 0

.. -> src

    >>> open('paste.ini', 'w').write(src)

Now, if we run the app, the request won't be retried:

    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> try: testapp.get('/conflict')
    ... except ZODB.POSException.ConflictError: pass
    ... else: print 'oops'
    Conflict!

Using non-thread-aware (non thread-local) transaction managers
--------------------------------------------------------------

By default, the middleware uses a thread-aware transaction manager::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb>
        <demostorage>
        </demostorage>
      </zodb>
   initializer = zc.zodbwsgi.tests:initialize_demo_db

.. -> src

    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> print testapp.get("/tm").body
    thread tm: True
    >>> print testapp.get("/tm").body
    thread tm: True


This can be controlled via the ``thread_transaction_manager`` key::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb>
        <demostorage>
        </demostorage>
      </zodb>
   initializer = zc.zodbwsgi.tests:initialize_demo_db
   thread_transaction_manager = false

.. -> src

    >>> open('paste.ini', 'w').write(src)
    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> print testapp.get("/tm").body
    thread tm: False


.. Other tests of corner cases:

  ::

    class demo_app:
        def __init__(self, default):
            pass
        def __call__(self, environ, start_response):
            start_response('200 OK', [('content-type', 'text/html')])
            root = environ['connection'].root()
            path = environ['PATH_INFO']
            if path == '/inc':
                root['x'] = root.get('x', 0) + 1
                environ['manager'].get().note('path: %r' % path)

            return [repr(root)]

  .. -> src

   >>> exec(src, zc.zodbwsgi.tests.__dict__)

  ::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb>
        <demostorage>
        </demostorage>
      </zodb>

   key = connection
   transaction_key = manager

  .. -> src

    >>> open('paste.ini', 'w').write(src)
    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> testapp.get('/inc')
    <200 OK text/html body="{'x': 1}">


demostorage_manage_header
-------------------------

Providing an value for this options enables hooks that allow one to push/pop
the underlying demostorage.

  ::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb>
        <demostorage>
        </demostorage>
      </zodb>

   key = connection
   transaction_key = manager
   demostorage_manage_header = X-FOO

  .. -> src

    >>> open('paste.ini', 'w').write(src)
    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> testapp.get('/inc')
    <200 OK text/html body="{'x': 1}">

If the push or pop header is provided, the middleware returns a response
immediately without sending it to the end of the pipeline.

    >>> testapp.get('/', {}, headers={'X-FOO': 'push'}).body
    'Demostorage pushed\n'

    >>> testapp.get('/inc')
    <200 OK text/html body="{'x': 2}">

    >>> testapp.get('/', {}, {'X-FOO': 'pop'}).body
    'Demostorage popped\n'

    >>> testapp.get('/')
    <200 OK text/html body="{'x': 1}">

This also works with multiple dbs.

  ::

    class demo_app:
        def __init__(self, default):
            pass
        def __call__(self, environ, start_response):
            start_response('200 OK', [('content-type', 'text/html')])
            path = environ['PATH_INFO']
            root_one = environ['connection'].get_connection('one').root()
            root_two = environ['connection'].get_connection('two').root()
            if path == '/inc':
                root_one['x'] = root_one.get('x', 0) + 1
                root_two['y'] = root_two.get('y', 0) + 1
                environ['manager'].get().note('path: %r' % path)

            data = {'one': root_one,
                    'two': root_two}

            return [repr(data)]

  .. -> src

   >>> exec(src, zc.zodbwsgi.tests.__dict__)

  ::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb one>
        <demostorage>
        </demostorage>
      </zodb>
      <zodb two>
        <demostorage>
        </demostorage>
      </zodb>

   key = connection
   transaction_key = manager
   demostorage_manage_header = X-FOO

  .. -> src

    >>> open('paste.ini', 'w').write(src)
    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    >>> testapp = webtest.TestApp(app)
    >>> testapp.get('/inc').body
    "{'two': {'y': 1}, 'one': {'x': 1}}"

    >>> testapp.get('/', {}, {'X-FOO': 'push'}).body
    'Demostorage pushed\n'

    >>> testapp.get('/inc').body
    "{'two': {'y': 2}, 'one': {'x': 2}}"

    >>> testapp.get('/', {}, {'X-FOO': 'pop'}).body
    'Demostorage popped\n'

    >>> testapp.get('/').body
    "{'two': {'y': 1}, 'one': {'x': 1}}"


If the storage of any of the databases is not a demostorage, an error is
returned.

  ::

   [app:main]
   paste.app_factory = zc.zodbwsgi.tests:demo_app
   filter-with = zodb

   [filter:zodb]
   use = egg:zc.zodbwsgi
   configuration =
      <zodb one>
        <demostorage>
        </demostorage>
      </zodb>
      <zodb two>
        <filestorage>
          path /tmp/Data.fs
        </filestorage>
      </zodb>

   key = connection
   transaction_key = manager
   demostorage_manage_header = foo

  .. -> src

    >>> open('paste.ini', 'w').write(src)
    >>> app = paste.deploy.loadapp('config:'+os.path.abspath('paste.ini'))
    ... #doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
      ...
    UserError: Attempting to activate demostorage hooks when one of the
    storages is not a DemoStorage

Limiting the number of connections
----------------------------------

If you're using a threaded server, one that dedicates a thread to each
active request, you can limit the number of simultaneous database
connections by specifying the number with the ``max_connections``
option.

(This only works for threaded servers because it uses threaded
semaphores. In the future, support for other locking mechanisms, such
as gevent Semaphores, may be added. In the mean time, if you're
inclined to monkey patch, you can replace ``zc.zodbwsgi.Semaphore``
with an alternative semaphore implementation, like gevent's.)

.. test

    >>> import threading, zc.thread, time
    >>> events = []
    >>> def app(environ, start_response):
    ...     event = threading.Event()
    ...     events.append(event)
    ...     event.wait(30)
    ...     start_response('200 OK', [])
    ...     return ''

    >>> f = zc.zodbwsgi.make_filter(
    ...     app, {}, '<zodb>\n<mappingstorage>\n</mappingstorage>\n</zodb>',
    ...     max_connections='1', retry=0)

    Now, we've said to only allow 1 connection. If we make requests in
    threads, only one will be active at a time.

    >>> @zc.thread.Thread
    ... def t1():
    ...     webtest.TestApp(f).get('/')

    >>> @zc.thread.Thread
    ... def t2():
    ...     webtest.TestApp(f).get('/')

    >>> @zc.thread.Thread
    ... def t3():
    ...     webtest.TestApp(f).get('/')

    >>> time.sleep(.01)

    Even though there are 3 requests out standing, only 1 has made it
    to the app:

    >>> len(events)
    1

    If we complete one, the next will be handled:

    >>> events.pop().set()
    >>> time.sleep(.01)

    >>> len(events)
    1

 and so on:

    >>> events.pop().set()
    >>> time.sleep(.01)

    >>> len(events)
    1

    >>> events.pop().set()
    >>> time.sleep(.01)

    >>> len(events)
    0

    >>> t1.join()
    >>> t2.join()
    >>> t3.join()

 Check the no-transaction case:

    >>> f = zc.zodbwsgi.make_filter(
    ...     app, {}, '<zodb>\n<mappingstorage>\n</mappingstorage>\n</zodb>',
    ...     max_connections='1', retry=0, transaction_management='False')

    >>> @zc.thread.Thread
    ... def t1():
    ...     webtest.TestApp(f).get('/')

    >>> @zc.thread.Thread
    ... def t2():
    ...     webtest.TestApp(f).get('/')

    >>> @zc.thread.Thread
    ... def t3():
    ...     webtest.TestApp(f).get('/')

    >>> time.sleep(.01)
    >>> len(events)
    1
    >>> events.pop().set()
    >>> time.sleep(.01)
    >>> len(events)
    1
    >>> events.pop().set()
    >>> time.sleep(.01)
    >>> len(events)
    1
    >>> events.pop().set()
    >>> time.sleep(.01)
    >>> len(events)
    0
    >>> t1.join()
    >>> t2.join()
    >>> t3.join()

 Verify that we can monkey patch:

    >>> def app(environ, start_response):
    ...     start_response('200 OK', [])
    ...     return ''
    >>> import mock
    >>> with mock.patch("zc.zodbwsgi.Semaphore") as Semaphore:
    ...     f = zc.zodbwsgi.make_filter(
    ...         app, {}, '<zodb>\n<mappingstorage>\n</mappingstorage>\n</zodb>',
    ...         max_connections='99', retry=0, transaction_management='False')
    ...     Semaphore.assert_called_with(99)
    ...     _ = webtest.TestApp(f).get('/')
    ...     Semaphore.return_value.acquire.assert_called_with()
    ...     Semaphore.return_value.release.assert_called_with()

Escaping connection and transaction management
----------------------------------------------

Normally, having connections and transactions managed for you is
convenient. Sometimes, however, you want to take over transaction
management yourself.

If you close ``environ['zodb.connection']``, then it won't be closed
by ``zc.zodbwsgi``, nor will ``zc.zodbwsgi`` commit or abort the
transaction it started.  If you're using ``max_connections``, closing
``environ['zodb.connection']`` will make the connection available for
other requests immediately, rather than waiting for your request to
complete.

.. test

  Normal (no error):

    >>> import sys
    >>> def app(environ, start_response):
    ...     print 'about to close'
    ...     environ['zodb.connection'].close()
    ...     print 'closed'
    ...     start_response('200 OK', [])
    ...     return ''

    >>> with mock.patch('transaction.manager') as manager:
    ...     with mock.patch("zc.zodbwsgi.Semaphore") as Semaphore:
    ...             f = zc.zodbwsgi.make_filter(
    ...                 app, {},
    ...                 '<zodb>\n<mappingstorage>\n</mappingstorage>\n</zodb>',
    ...                 max_connections='99', retry=0)
    ...             Semaphore.assert_called_with(99)
    ...             Semaphore.return_value.acquire.side_effect = (
    ...                 lambda : sys.stdout.write('acquire\n'))
    ...             Semaphore.return_value.release.side_effect = (
    ...                 lambda : sys.stdout.write('release\n'))
    ...             manager.begin.side_effect = (
    ...                 lambda : sys.stdout.write('begin\n'))
    ...             manager.commit.side_effect = (
    ...                 lambda *a: sys.stdout.write('commit\n'))
    ...             manager.abort.side_effect = (
    ...                 lambda *a: sys.stdout.write('abort\n'))
    ...             _ = webtest.TestApp(f).get('/')
    acquire
    begin
    about to close
    release
    closed

  Error:

    >>> def app(environ, start_response):
    ...     print 'about to close'
    ...     environ['zodb.connection'].close()
    ...     print 'closed'
    ...     raise ValueError('Fail')

    >>> with mock.patch('transaction.manager') as manager:
    ...     with mock.patch("zc.zodbwsgi.Semaphore") as Semaphore:
    ...             f = zc.zodbwsgi.make_filter(
    ...                 app, {},
    ...                 '<zodb>\n<mappingstorage>\n</mappingstorage>\n</zodb>',
    ...                 max_connections='99', retry=0)
    ...             Semaphore.assert_called_with(99)
    ...             Semaphore.return_value.acquire.side_effect = (
    ...                 lambda : sys.stdout.write('acquire\n'))
    ...             Semaphore.return_value.release.side_effect = (
    ...                 lambda : sys.stdout.write('release\n'))
    ...             manager.begin.side_effect = (
    ...                 lambda : sys.stdout.write('begin\n'))
    ...             manager.commit.side_effect = (
    ...                 lambda *a: sys.stdout.write('commit\n'))
    ...             manager.abort.side_effect = (
    ...                 lambda *a: sys.stdout.write('abort\n'))
    ...             try: webtest.TestApp(f).get('/')
    ...             except ValueError: pass
    acquire
    begin
    about to close
    release
    closed


Dealing with the occasional long-running requests
-------------------------------------------------

Database connections can be pretty expensive resources, especially if
they have large database caches.  For this reason, when using large
caches, it's common to limit the number of application threads, to
limit the number of connections used.  If your application is compute
bound, you generally want to use one application thread per process
and a process per processor on the host machine.

If your application itself makes network requests (e.g calling
external service APIs), so it's network/server bound rather than
compute bound, you should increase the number of application threads
and decrease the size of the connection caches to compensate.

If your application is mostly compute bound, but sometimes calls
external services, you can take a hybrid approach:

- Increase the number of application threads.
- Set ``max_connections`` to 1.
- In the parts of your application that make external service calls:

  - Close ``environ['zodb.connection']``, committing first, if
    necessary.
  - Make your service calls.
  - Open and close ZODB connections yourself when you need to use the
    database.

    If you're using ZEO or relstorage, you might want to create
    separate database clients for use in these calls, configured with
    smaller caches.

Changes
=======

1.0.0 (2013-09-15)
------------------

- Added support for occasional long-running requests:

  - You can limit the number of database connections with
    max_connections.

  - You can take over connection and transaction management to release
    connections while blocking (typically when calling external
    services).

- Add an option to use a thread-aware transaction manager, and make it
  the default.


0.3.0 (2013-03-07)
------------------

- Using the demostorage hook now returns a response immediately without
  processing the rest of the pipeline. Makes use of this feature less
  confusing.

0.2.1 (2013-03-06)
------------------

- Fix reference to a file that was renamed.

0.2.0 (2013-03-06)
------------------

- Add hooks to manage (push/pop) underlying demostorage based on headers.
- Refactor filter to use instance attributes instead of a closure.

0.1.0 (2010-02-16)
------------------

Initial release



.. [#multidb] If you want to use multiple ZODB databases, you can
   simply define them in your configuration option.  Just make sure to
   give them names.  When you want to access a database, use the
   ``get_connection`` method on the connection in the environment::

      foo_conn = environ['zodb.connection'].get_connection('foo')
