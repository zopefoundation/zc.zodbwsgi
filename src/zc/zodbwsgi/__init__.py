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
import ZODB.config
from ZODB.DB import DB
from zope.exceptions.interfaces import UserError

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
            demostorage_manage_header=None):

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

        header = (demostorage_manage_header or
                default.get('demostorage_manage_header'))
        if header is not None:
            for d in self.database.databases.values():
                if not isinstance(d.storage, ZODB.DemoStorage.DemoStorage):
                    raise UserError(
                        "Attempting to activate demostorage hooks when "
                        "one of the storages is not a DemoStorage")
        self.demostorage_manage_header = header and header.replace('-', '_')

    def __call__(self, environ, start_response):
        if self.demostorage_manage_header is not None:
            action = environ.get('HTTP_' + self.demostorage_manage_header)
            if action == 'push':
                databases = {}
                for name, db in self.database.databases.items():
                    DB(db.storage.push(),
                       databases=databases,
                       database_name=name)
                self.database = databases[self.database.database_name]
            elif action == 'pop':
                databases = {}
                for name, db in self.database.databases.items():
                    DB(db.storage.pop(),
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
        demostorage_manage_header=None):
    db_app =  DatabaseFilter(app,
        default,
        configuration,
        initializer=initializer,
        key=key,
        transaction_management=transaction_management,
        transaction_key=transaction_key,
        demostorage_manage_header=demostorage_manage_header)
    retry = int(retry or default.get('retry', '3'))
    if retry > 0:
        retry_app = repoze.retry.Retry(db_app, tries=retry+1)
        retry_app.database = db_app.database
        return retry_app
    return db_app

