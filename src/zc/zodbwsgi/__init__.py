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
import ZODB.config

booleans = dict(true=True, false=False)

def Factory(application, default,
            configuration,
            initializer=None,
            key=None,
            transaction_management=None,
            transaction_key=None,
            retry=None,
            max_memory_retry_buffer_size=1<<20,
            ):
    db = ZODB.config.databaseFromString(configuration)

    initializer = initializer or default.get('initializer')
    if initializer:
        module, expr = initializer.split(':', 1)
        if module:
            d = __import__(module, {}, {}, ['*']).__dict__
        else:
            d={}
        initializer = eval(expr, d)
        initializer(db)

    key = key or default.get('key', 'zodb.connection')

    transaction_management = booleans[
        transaction_management or default.get(
            'transaction_management', 'true').lower()]

    if transaction_management:
        transaction_key = transaction_key or default.get(
            'transaction_key', 'transaction.manager')
        def dbapp(environ, start_response):
            tm = environ[transaction_key] = transaction.TransactionManager()
            conn = environ[key] = db.open(tm)
            try:
                try:
                    result = application(environ, start_response)
                except:
                    tm.get().abort()
                    raise
                else:
                    tm.get().commit()
                return result
            finally:
                conn.close()
                del environ[transaction_key]
                del environ[key]

    else:
        def dbapp(environ, start_response):
            conn = environ[key] = db.open()
            try:
                return application(environ, start_response)
            finally:
                conn.close()
                del environ[key]

    retry = int(retry or default.get('retry', '3'))
    if retry > 0:
        dbapp = repoze.retry.Retry(dbapp, tries=retry+1)
    dbapp.database = db

    return dbapp

