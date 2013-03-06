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

import repoze.retry
import transaction
import ZODB.DemoStorage
from ZODB.DB import DB
import ZODB.config

booleans = dict(true=True, false=False)

class DatabaseFilter(object):

    def __init__(self,
            application,
            default,
            configuration,
            initializer=None,
            key=None,
            transaction_management=None,
            transaction_key=None,
            demostorage_manage_prefix=None):

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

        self.transaction_management = booleans[
            transaction_management or default.get(
                'transaction_management', 'true').lower()]

        self.transaction_key = transaction_key or default.get(
                'transaction_key', 'transaction.manager')

        self.demostorage_management = booleans[
            transaction_management or default.get(
                'transaction_management', 'true').lower()]

        self.demostorage_prefix = None
        if isinstance(self.database.storage, ZODB.DemoStorage.DemoStorage):
            self.demostorage_prefix = (demostorage_manage_prefix or
                default.get('demostorage_manage_prefix'))


    def __call__(self, environ, start_response):
        if self.demostorage_prefix is not None:
            if ('%s.push' % self.demostorage_prefix) in environ:
                databases = {}
                for name, db in self.database.databases.items():
                    DB(self.database.storage.push(),
                       databases=databases,
                       database_name=name)
                self.database = databases[self.database.database_name]
            elif ('%s.pop' % self.demostorage_prefix) in environ:
                databases = {}
                for name, db in self.database.databases.items():
                    DB(self.database.storage.pop(),
                       databases=databases,
                       database_name=name)
                self.database = databases[self.database.database_name]
        if self.transaction_management:
            tm = environ[self.transaction_key] = transaction.TransactionManager()
            conn = environ[self.key] = self.database.open(tm)
            try:
                try:
                    result = self.application(environ, start_response)
                except:
                    tm.get().abort()
                    raise
                else:
                    tm.get().commit()
                return result
            finally:
                conn.close()
                del environ[self.transaction_key]
                del environ[self.key]

        else:
            conn = environ[self.key] = self.database.open()
            try:
                return self.application(environ, start_response)
            finally:
                conn.close()
                del environ[self.key]

def make_filter(app,
        default,
        configuration,
        initializer=None,
        key=None,
        transaction_management=None,
        transaction_key=None,
        retry=None,
        max_memory_retry_buffer_size=1<<20,
        demostorage_manage_prefix=None):
    db_app =  DatabaseFilter(app,
        default,
        configuration,
        initializer=initializer,
        key=key,
        transaction_management=transaction_management,
        transaction_key=transaction_key,
        demostorage_manage_prefix=demostorage_manage_prefix)
    retry = int(retry or default.get('retry', '3'))
    if retry > 0:
        retry_app = repoze.retry.Retry(db_app, tries=retry+1)
        retry_app.database = db_app.database
        return retry_app
    return db_app

