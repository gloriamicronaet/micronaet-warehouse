#!/usr/bin/python
# -*- coding: utf-8 -*-
###############################################################################
#
# ODOO (ex OpenERP)
# Open Source Management Solution
# Copyright (C) 2001-2015 Micronaet S.r.l. (<https://micronaet.com>)
# Developer: Nicola Riolini @thebrush (<https://it.linkedin.com/in/thebrush>)
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

import os
import sys
import logging
import openerp
import openerp.netsvc as netsvc
import openerp.addons.decimal_precision as dp
from openerp.osv import fields, osv, expression, orm
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from openerp import SUPERUSER_ID, api
from openerp import tools
from openerp.tools.translate import _
from openerp.tools.float_utils import float_round as round
from openerp.tools import (DEFAULT_SERVER_DATE_FORMAT,
    DEFAULT_SERVER_DATETIME_FORMAT,
    DATETIME_FORMATS_MAP,
    float_compare)


_logger = logging.getLogger(__name__)


class WarehouseShelf(orm.Model):
    """ Model name: Warehouse shelf
    """
    _name = 'warehouse.shelf'
    _description = 'Magazzino automatico'
    _order = 'name'

    # Utility:
    def get_command_filename(self, cr, uid, ids, context=None):
        """ Extract filename from configuration
            @return directly open file for output
        """
        shelf = self.browse(cr, uid, ids, context=context)[0]
        path = os.path.expanduser(shelf.folder)
        filename = shelf.filename
        if not filename:
            filename = ('extract_job_%s.csv' % datetime.now())\
                .replace('/', '_').replace(':', '_')
        fullname = os.path.join(path, filename)
        _logger.warning('Generate command file: %s' % fullname)
        return open(fullname, 'w')

    def generate_warehouse_job(self, cr, uid, mode, extract_job, context=None):
        """ Generate warehouse job for extract data
            self: instance
            cr: db cursor
            uid: user ID
            mode: 'check' = open slot
                  'load' = load product in product_slot with quantity
                  'unload' = load product in product_slot with quantity
            extract_job: normal record is = [
                         slot browse, (both)
                         product browse,  (used only load / unload)
                         product slot browse,  (used only load / unload)
                         quantity,  (used only load / unload)
                         ]
            context: parameters
        """
        operation = 'P'
        access = '1'
        for shelf in extract_job:
            job_text = ''
            for record in extract_job[shelf]:
                slot, product, product_slot, quantity = record

                if mode == 'check':
                    job_text += '%s;%s;%s;%s\n' % (
                        operation,
                        access,
                        slot.name,
                        '' if not product else product.default_code,
                    )

                elif mode in ('unload', 'load'):
                    slot, product, product_slot, quantity = record
                    if mode == 'unload':
                        sign = -1
                    else:
                        sign = +1
                    # quantity *= sign

                    job_text += '%s;%s;%s;%s\n' % (
                        operation,
                        access,
                        slot.name,
                        product_slot.position or product.default_code or '',
                    )
                else:
                    _logger.error('Call procedure in wrong mode: %s' % mode)

            if job_text:  # Keep as fast as possible at the end or shelf:
                job_file = self.get_command_filename(
                    cr, uid, [shelf.id], context=context)
                job_file.write(job_text)
                job_file.close()
        return True

    # Button events:
    def generate_all_slot(self, cr, uid, ids, context=None):
        """ Generate all slot depend on shelf configuration
        """
        slot_pool = self.pool.get('warehouse.shelf.slot')
        shelf_id = ids[0]
        shelf = self.browse(cr, uid, shelf_id, context=context)

        cells = []
        for draw in range(1, shelf.slots + 1):
            name = str(draw)
            cells.append((draw, name))

        # Create or update cells block:
        slot_ids = slot_pool.search(cr, uid, [
            ('shelf_id', '=', shelf_id),
        ], context=context)
        slot_pool.write(cr, uid, slot_ids, {
            'active': False,
        }, context=context)

        for slot in sorted(cells):
            sequence, name = slot
            slot_ids = slot_pool.search(cr, uid, [
                ('shelf_id', '=', shelf_id),
                ('name', '=', name),
            ], context=context)
            if slot_ids:
                slot_pool.write(cr, uid, slot_ids, {
                    'active': True,
                    'sequence': sequence,
                }, context=context)
            else:
                slot_pool.create(cr, uid, {
                    'active': True,
                    'shelf_id': shelf_id,
                    'name': name,
                    'sequence': sequence,
                }, context=context)
        _logger.warning('Created %s slot for this shelf' % len(cells))
        return True

    _columns = {
        'active': fields.boolean(
            'Attivo'),
        'name': fields.char(
            'Magazzino automatico', size=60, required=True),
        'company_id': fields.many2one(
            'res.company', 'Azienda', required=True),

        # Setup:
        'slots': fields.integer(
            'Cassetti', required=True),

        # Management:
        'folder': fields.char(
            'Cartella output', size=180, required=True,
            help='Utilizzare anche il percorso da cartella utente es.: '
                 '~/nas/cartella/output'),
        'filename': fields.char(
            'Filename', size=50,
            help='Se indicato il filename viene sempre estratto un file fisso,'
                 'nel caso non si indichi viene generato un nome file con '
                 'il timestamp del momento di richiesta.'),
        'separator': fields.char('Separatore', size=5),
        'note': fields.text('Note'),
        }

    _defaults = {
        'separator': lambda *x: ';',
        'active': lambda *x: True,
    }


class WarehouseShelfSlot(orm.Model):
    """ Model name: Warehouse shelf slot
    """
    _name = 'warehouse.shelf.slot'
    _description = 'Cassetto magazzino automatico'
    _order = 'sequence, alias, name'

    # Button event:
    def open_this_slot(self, cr, uid, ids, context=None):
        """ Open this slot just for check (without detail)
        """
        shelf_pool = self.pool.get('warehouse.shelf')

        extract_job = {}
        for slot in self.browse(cr, uid, ids, context=context):
            shelf = slot.shelf_id
            if shelf not in extract_job:
                extract_job[shelf] = []
            extract_job[shelf].append((
                slot,  # Slot obj
                False,  # Product obj
                False,  # Product slot obj (not mandatory)
                False,  # Q.
            ))
        return shelf_pool.generate_warehouse_job(extract_job)

    _columns = {
        'sequence': fields.integer('Seq.'),
        'active': fields.boolean('Attivo'),
        'name': fields.char(
            'Cassetto magazzino', size=60,
            help='Genericamente il nome è dato dalle coordinate: x-y-z'),
        'alias': fields.char(
            'Alias', size=60,
            help='Nome alternativo per chiamare lo slot del magazzino'),
        'shelf_id': fields.many2one('warehouse.shelf', 'Magazzino'),
        'note': fields.text('Note')
        }

    _defaults = {
        'active': lambda *x: True,
    }


class ProductProductSlot(orm.Model):
    """ Model name: Product product slot part
    """
    _name = 'product.product.slot'
    _description = 'Raggruppamento prodotti'
    _rec_name = 'slot_id'
    _order = 'slot_id'

    def open_product_slot(self, cr, uid, ids, context=None):
        """ Open this slot just for check (with detail product in it)
        """
        shelf_pool = self.pool.get('warehouse.shelf')

        extract_job = {}
        for product_slot in self.browse(cr, uid, ids, context=context):
            shelf = product_slot.slot_id.shelf_id
            if shelf not in extract_job:
                extract_job[shelf] = []
            extract_job[shelf].append((
                product_slot.slot_id,  # Slot obj
                product_slot.product_id,  # Product obj
                product_slot,  # Product slot obj (not mandatory)
                False,
            ))
        return shelf_pool.generate_warehouse_job(extract_job)

    _columns = {
        'product_id': fields.many2one('product.product', 'Prodotto'),
        'slot_id': fields.many2one('warehouse.shelf.slot', 'Cassetto'),
        'shelf_id': fields.related(
            'slot_id', 'shelf_id', type='many2one',
            string='Magazzino', relation='warehouse.shelf',
            store=True,
        ),
        'position': fields.char(
            'Posizione', size=30,
            help='Posizione all\'interno del cassetto, es. B1'),
        'quantity': fields.float('Q.', digits=(10, 2)),
        'note': fields.text('Note'),
    }


class ProductProduct(orm.Model):
    """ Extend product
    """
    _inherit = 'product.product'

    def get_all_warehouse_product(self, cr, uid, ids, context=None):
        """ List of all product and return result
        """

        # model_pool = self.pool.get('ir.model.data')
        # view_id = model_pool.get_object_reference(
        #    cr, uid, 'module_name', 'view_name')[1]
        tree_view_id = form_view_id = False

        status_pool = self.pool.get('product.product.slot')
        status_ids = status_pool.search(cr, uid, [], context=context)
        status_proxy = status_pool.browse(cr, uid, status_ids, context=context)
        product_ids = [item.product_id.id for item in status_proxy]

        return {
            'type': 'ir.actions.act_window',
            'name': _('Prodotti attivi'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            # 'res_id': 1,
            'res_model': 'product.product',
            'view_id': tree_view_id,
            'views': [(tree_view_id, 'tree'), (form_view_id, 'form')],
            'domain': [('id', '=', product_ids)],
            'context': context,
            'target': 'current',
            'nodestroy': False,
            }

    _columns = {
        'product_slot_ids': fields.one2many(
            'product.product.slot', 'product_id', 'Disposizione'),
    }


class StockPicking(orm.Model):
    """ Extend stock picking
    """
    _inherit = 'stock.picking'

    # Button event:
    def extract_all_document_warehouse(self, cr, uid, ids, context=None):
        """ Generate all file from product in picking for manage auto feed
            from warehouse shelf
        """
        return True


class ResCompany(orm.Model):
    """ Extend company
    """
    _inherit = 'res.company'

    _columns = {
        'shelf_ids': fields.one2many(
            'warehouse.shelf', 'company_id', 'Magazzini automatici'),
    }


class WarehouseShelfRelations(orm.Model):
    """ Model name: Warehouse shelf
    """
    _inherit = 'warehouse.shelf'

    _columns = {
        'slot_ids': fields.one2many(
            'warehouse.shelf.slot', 'shelf_id', 'Celle magazzino'),
    }
