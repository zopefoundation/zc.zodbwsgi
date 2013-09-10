##############################################################################
#
# Copyright 2010 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################

from threading import Semaphore

import repoze.retry
import transaction
import ZODB.DemoStorage
import ZODB.config
from ZODB.DB import DB
from zope.exceptions.interfaces import UserError

to_bool = lambda val: {"true": True, "false": False}[val.lower()]

class DatabaseFilter(object):

    def __init__(
        self,
        application,
        default,
        configuration,
        initializer=None,
        key=None,
        transaction_management=None,
        transaction_key=None,
        thread_transaction_manager=None,
        demostorage_manage_header=None,
        max_connections=None,
        ):

        self.application = application
        self.database = ZODB.config.databaseFromString(configuration)

        initializer = initializer or default.get('initializer')
        if initializer:
            module, expr = initializer.split(':', 1)
            if module:
                d = __import__(module, {}, {}, ['*']).__dict__
            else:
                d={}
            initializer = eval(expr, d)
            initializer(self.database)

        self.key = key or default.get('key', 'zodb.connection')

        self.transaction_management = to_bool(
                transaction_management or
                default.get('transaction_management', 'true'))

        self.transaction_key = transaction_key or default.get(
                'transaction_key', 'transaction.manager')

        self.thread_transaction_manager = to_bool(
                thread_transaction_manager or
                default.get("thread_transaction_manager", "true"))

        self.demostorage_management = to_bool(
                transaction_management or
                default.get('transaction_management', 'true'))

        header = (demostorage_manage_header or
                default.get('demostorage_manage_header'))
        if header is not None:
            for d in self.database.databases.values():
                if not isinstance(d.storage, ZODB.DemoStorage.DemoStorage):
                    raise UserError(
                        "Attempting to activate demostorage hooks when "
                        "one of the storages is not a DemoStorage")
        self.demostorage_manage_header = header and header.replace('-', '_')

        if max_connections:
            sem = Semaphore(int(max_connections))
            self.acquire = sem.acquire
            self.release = sem.release

    def __call__(self, environ, start_response):
        if self.demostorage_manage_header is not None:
            # XXX See issue #3 regarding current implementation and Jim's
            # suggestions::
            #
            #     https://github.com/zopefoundation/zc.zodbwsgi/issues/3

            action = environ.get('HTTP_' + self.demostorage_manage_header)
            status = '200 OK'
            response_headers = [('Content-type', 'text/plain')]
            if action == 'push':
                databases = {}
                for name, db in self.database.databases.items():
                    DB(db.storage.push(),
                       databases=databases,
                       database_name=name)
                self.database = databases[self.database.database_name]
                start_response(status, response_headers)
                return ['Demostorage pushed\n']
            elif action == 'pop':
                databases = {}
                for name, db in self.database.databases.items():
                    DB(db.storage.pop(),
                       databases=databases,
                       database_name=name)
                self.database = databases[self.database.database_name]
                start_response(status, response_headers)
                return ['Demostorage popped\n']


        closed = []
        try:
            self.acquire()
            if self.transaction_management:
                if self.thread_transaction_manager:
                    tm = transaction.manager
                else:
                    tm = transaction.TransactionManager()
                environ[self.transaction_key] = tm
            else:
                tm = None

            conn = environ[self.key] = self.database.open(tm)

            @conn.onCloseCallback
            def on_close():
                closed.append(1)
                self.release()

            try:
                if tm:
                    try:
                        tm.begin()
                        result = self.application(environ, start_response)
                    except:
                        if not closed:
                            tm.abort()
                        raise
                    else:
                        if not closed:
                            tm.commit()
                        return result

                else:
                    return self.application(environ, start_response)

            finally:
                if not closed:
                    conn.close()
                environ.pop(self.transaction_key, 0)
                del environ[self.key]

        finally:
            if not closed:
                self.release()

    def acquire(self):
        pass
    release = acquire

def make_filter(
    app,
    default,
    configuration,
    initializer=None,
    key=None,
    transaction_management=None,
    transaction_key=None,
    thread_transaction_manager=None,
    retry=None,
    max_memory_retry_buffer_size=1<<20,
    demostorage_manage_header=None,
    max_connections=None,
    ):
    db_app =  DatabaseFilter(
        app,
        default,
        configuration,
        initializer=initializer,
        key=key,
        transaction_management=transaction_management,
        transaction_key=transaction_key,
        thread_transaction_manager=thread_transaction_manager,
        demostorage_manage_header=demostorage_manage_header,
        max_connections=max_connections)
    retry = int(retry or default.get('retry', '3'))
    if retry > 0:
        retry_app = repoze.retry.Retry(db_app, tries=retry+1)
        retry_app.database = db_app.database
        return retry_app
    return db_app

