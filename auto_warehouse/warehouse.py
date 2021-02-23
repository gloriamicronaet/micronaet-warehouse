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

    # Button events:
    def generate_all_slot(self, cr, uid, ids, context=None):
        """ Generate all slot depend on shelf configuration
        """
        # TODO
        return True

    _columns = {
        'active': fields.boolean(
            'Attivo'),
        'name': fields.char(
            'Magazzino automatico', size=60, required=True),
        'company_id': fields.many2one(
            'res.company', 'Azienda', required=True),

        # Setup:
        'x_axis': fields.integer(
            'Asse X', help='Colonne', required=True),
        'y_axis': fields.integer(
            'Asse Y', help='Piani', required=True),
        'z_axis': fields.integer(
            'Asse Z', help='Parti del cassetto'),

        # Management:
        'folder': fields.char(
            'Cartella output', size=180, required=True,
            help='Utilizzare anche il percorso da cartella utente es.:'
                 ' ~/nas/cartella/output'),
        'filename': fields.char(
            'Filename', size=50,
            help='Se indicato il filename viene sempre estratto un file fisso,'
                 'nel caso non si indichi viene generato un nome file con '
                 'il timestamp del momento di richiesta.'),
        'separator': fields.char('Separatore', size=5),
        }

    _defaults = {
        'separator': lambda *x: ';',
    }


class WarehouseShelfSlot(orm.Model):
    """ Model name: Warehouse shelf slot
    """
    _name = 'warehouse.shelf.slot'
    _description = 'Cella magazzino automatico'
    _order = 'name, alias'

    # Button event:
    def open_this_slot(self, cr, uid, ids, context=None):
        """ Open this slot
        """
        return True

    _columns = {
        'active': fields.boolean('Attivo'),
        'name': fields.char(
            'Slot magazzino', size=60,
            help='Genericamente il nome è dato dalle coordinate: x-y-z'),
        'alias': fields.char(
            'Alias', size=60,
            help='Nome alternativo per chiamare lo slot del magazzino'),
        'shelf_id': fields.many2one('warehouse.shelf', 'Magazzino'),
        }


class ProductProductSlot(orm.Model):
    """ Model name: Product product slot part
    """
    _name = 'product.product.slot'
    _description = 'Raggruppamento prodotti'
    _rec_name = 'slot_id'
    _order = 'id'

    _columns = {
        'slot_id': fields.many2one('warehouse.shelf.slot', 'Slot'),
        'product_id': fields.many2one('product.product', 'Prodotto'),
        'quantity': fields.float('Q.', size=(10, 2)),
        'note': fields.text('Note')
    }


class ProductProduct(orm.Model):
    """ Extend product
    """
    _inherit = 'product.product'

    _columns = {
        'product_slot_ids': fields.many2one(
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
        'shelf_ids': fields.many2one(
            'warehouse.shelf', 'company_id', 'Magazzini automatici'),
    }


class WarehouseShelfRelations(orm.Model):
    """ Model name: Warehouse shelf
    """
    _inherit = 'warehouse.shelf'

    _columns = {
        'slot_ids': fields.many2one(
            'warehouse.shelf.slot', 'shelf_id', 'Celle magazzino'),
    }
