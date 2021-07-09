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
import pdb

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
                .replace('-', '_').replace(':', '_')
        fullname = os.path.join(path, filename)
        _logger.warning('Generate command file: %s' % fullname)
        return open(fullname, 'w')

    def generate_warehouse_job(self, cr, uid, mode, extract_job, context=None):
        """ MASTER FUNCTION:
            Generate warehouse job for extract data
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
            if shelf.mode == 'manual':
                _logger.error('Cannot unload manual shelf!')
                continue
            job_text = ''
            for record in extract_job[shelf]:
                slot, product, product_slot, quantity = record

                if mode == 'check':
                    if product_slot:
                        comment = '%s > %s [%s]' % (
                            product_slot.position,
                            product_slot.product_id.default_code or '',
                            quantity or '/',
                        )
                    elif product:
                        comment = 'Controllo %s' % (
                            product.default_code or '',
                        )
                    else:
                        comment = 'Controllo cassetto: %s' % slot.name
                    job_text += '%s;%s;%s;%s\n' % (
                        operation,
                        access,
                        slot.name,
                        comment,
                    )

                elif mode in ('unload', 'load'):
                    slot, product, product_slot, quantity = record
                    if mode == 'unload':
                        sign = -1
                        mode_text = 'Scar.'
                    else:
                        sign = +1
                        mode_text = 'Car.'
                    # quantity *= sign

                    comment = '%s %s: %s [pos. %s]' % (
                        mode_text,
                        quantity,
                        product_slot.product_id.default_code or '',
                        product_slot.position,
                    )

                    job_text += '%s;%s;%s;%s\n' % (
                        operation,
                        access,
                        slot.name,
                        comment,
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
    def get_all_slot_warehouse(self, cr, uid, ids, context=None):
        """ List of all slot of this warehouse
        """
        shelf_id = ids[0]
        model_pool = self.pool.get('ir.model.data')
        # tree_view_id = model_pool.get_object_reference(
        #    cr, uid,
        #    'auto_warehouse', 'view_product_product_warehouse_tree')[1]
        tree_view_id = form_view_id = False

        slot_pool = self.pool.get('warehouse.shelf.slot')
        slot_ids = slot_pool.search(cr, uid, [
            ('shelf_id', '=', shelf_id),
            ('mode', '!=', 'removed'),
        ], context=context)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Cassetti attivi'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            # 'res_id': 1,
            'res_model': 'warehouse.shelf.slot',
            'view_id': tree_view_id,
            'views': [(tree_view_id, 'tree'), (form_view_id, 'form')],
            'domain': [('id', '=', slot_ids)],
            'context': context,
            'target': 'current',
            'nodestroy': False,
            }

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
        current_slot_ids = slot_pool.search(cr, uid, [
            ('shelf_id', '=', shelf_id),
        ], context=context)

        for slot in sorted(cells):
            sequence, name = slot
            slot_ids = slot_pool.search(cr, uid, [
                ('shelf_id', '=', shelf_id),
                ('name', '=', name),
            ], context=context)
            if slot_ids:
                slot = slot_pool.browse(cr, uid, slot_ids, context=context)[0]
                data = {
                    'sequence': sequence,
                    }
                if slot.mode == 'removed':
                    data['mode'] = 'load'
                slot_pool.write(cr, uid, slot_ids, data, context=context)
                current_slot_ids.remove(slot_ids[0])
            else:
                slot_pool.create(cr, uid, {
                    'shelf_id': shelf_id,
                    'name': name,
                    'sequence': sequence,
                }, context=context)
        _logger.warning('Created %s slot for this shelf' % len(cells))
        if current_slot_ids:
            slot_pool.write(cr, uid, current_slot_ids, {
                'mode': 'removed',
            }, context=context)
            _logger.warning('Removed %s slot for this shelf' % len(slot_ids))
        return True

    _columns = {
        'active': fields.boolean('Attivo'),
        'mode': fields.selection([
            ('auto', 'Automatico'),
            ('manual', 'Manuale'),
            ], 'Modalità',
            help='Indica se il magazzino scarica automaticamente le celle'),
        'name': fields.char(
            'Magazzino automatico', size=60, required=True),
        'code': fields.char(
            'Codice magazzino', size=10, required=True),
        'company_id': fields.many2one(
            'res.company', 'Azienda', required=True),

        # Setup:
        'slots': fields.integer('Cassetti'),

        # Management:
        'all_in_one': fields.boolean('Chiamta con file unico'),
        'folder': fields.char(
            'Cartella output', size=180,
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
        'all_in_one': lambda *x: True,
        'separator': lambda *x: ';',
        'active': lambda *x: True,
        'mode': lambda *x: 'auto',
    }


class WarehouseShelfSlot(orm.Model):
    """ Model name: Warehouse shelf slot
    """
    _name = 'warehouse.shelf.slot'
    _description = 'Cassetto magazzino automatico'
    _order = 'sequence, alias, name'

    # ORM override:
    def name_get(self, cr, uid, ids, context=None):
        """ Show extra data in foreign slot
        """
        res = []
        if not ids:
            return res
        for slot in self.browse(cr, uid, ids, context):
            shelf = slot.shelf_id

            res.append((slot.id, '%s - [%s] %s' % (
                slot.name,
                shelf.code or '?',
                '(man.)' if shelf.mode == 'manual' else '(aut.)',
            )))
        return res

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
        return shelf_pool.generate_warehouse_job(
            cr, uid, 'check', extract_job, context=context)

    _columns = {
        'sequence': fields.integer('Seq.'),
        'name': fields.char(
            'Cassetto magazzino', size=60,
            help='Genericamente il nome è dato dalle coordinate: x-y-z'),
        'alias': fields.char(
            'Alias', size=60,
            help='Nome alternativo per chiamare lo slot del magazzino'),
        'shelf_id': fields.many2one('warehouse.shelf', 'Magazzino'),
        'note': fields.text('Note'),
        'mode': fields.selection([
            ('load', 'Carico normale'),
            ('partner', 'Cliente fisso'),
            ('account', 'Commessa fissa'),
            ('temp', 'Temporaneo consegna'),
            ('removed', 'Rimosso'),
        ], 'Modalità', required=True),
        }

    _defaults = {
        'mode': lambda *x: 'load',
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
        if context is None:
            context = {}
        force_mode = context.get('force_mode')
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
                product_slot.quantity,
            ))

        return shelf_pool.generate_warehouse_job(
            cr, uid, force_mode or 'check', extract_job, context=context)

    _columns = {
        'product_id': fields.many2one('product.product', 'Prodotto'),
        'slot_id': fields.many2one(
            'warehouse.shelf.slot', 'Cassetto'),
        'shelf_id': fields.related(
            'slot_id', 'shelf_id', type='many2one',
            string='Magazzino', relation='warehouse.shelf',
            store=True,
        ),
        'position': fields.char(
            'Posizione', size=30,
            help='Posizione all\'interno del cassetto, es. B1'),
        'quantity': fields.float('Q.', digits=(10, 2)),
        'max_quantity': fields.float('Max Q.', digits=(10, 2)),
        'note': fields.text('Note'),
    }


class StockMoveSlot(orm.Model):
    """ Model name: Stock move slot
    """
    _name = 'stock.move.slot'
    _description = 'Movimento magazzino automatico'
    _order = 'sequence, id'
    _rec_name = 'product_slot_id'

    _columns = {
        'sequence': fields.integer('Seq.'),
        'picking_id': fields.many2one(
            'stock.picking', 'Picking',
            help='Collegamento al documento generatore', ondelete='cascade'),
        'move_id': fields.many2one(
            'stock.move', 'Movimento di magazzino',
            help='Collegamento al generatore', ondelete='cascade'),
        'product_id': fields.many2one(
            'product.product', 'Prodotto', readonly=True, ondelete='set null'),
        'product_slot_id': fields.many2one(
            'product.product.slot', 'Cella', ondelete='set null'),

        'move_quantity': fields.related(
            'move_id', 'product_uom_qty', type='float',
            digits=(10, 2), string='Q. movimento', readonly=True, store=True),
        'slot_quantity': fields.related(
            'product_slot_id', 'quantity', type='float',
            digits=(10, 2), string='Q. cella',
            readonly=True),  # TODO maybe not readonly!
        'slot_id': fields.related(
            'product_slot_id', 'slot_id', type='many2one',
            relation='warehouse.shelf.slot', string='Cassetto',
            readonly=True, store=True),
        'position': fields.related(
            'product_slot_id', 'position', type='char',
            size=30, string='Posizione', readonly=True, store=True),
        # Related Shelf?

        # Manage unload:
        'quantity': fields.float('Prelievo', digits=(10, 2)),
        'real_quantity': fields.float('Confermato', digits=(10, 2)),
        'state': fields.selection([
            ('draft', 'Bozza'),
            ('done', 'Completato'),
        ], 'Stato', readonly=True),
    }

    _defaults = {
        'state': lambda *x: 'draft',
    }


class StockPicking(orm.Model):
    """ Extend stock picking
    """
    _inherit = 'stock.picking'

    # Button event:
    def slot_picking_view(self, cr, uid, ids, context=None):
        """ Help picking view
        """
        picking_id = ids[0]
        model_pool = self.pool.get('ir.model.data')
        tree_view_id = model_pool.get_object_reference(
            cr, uid,
            'auto_warehouse', 'view_stock_move_slot_tree')[1]
        form_view_id = False

        ctx = context.copy()
        ctx['search_default_group_slot'] = True
        return {
            'type': 'ir.actions.act_window',
            'name': _('Movimentazioni'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            # 'res_id': 1,
            'res_model': 'stock.move.slot',
            'view_id': tree_view_id,
            'views': [(tree_view_id, 'tree'), (form_view_id, 'form')],
            'domain': [('picking_id', '=', picking_id)],
            'context': ctx,
            'target': 'current',
            'nodestroy': False,
            }

    def generate_warehouse_move_from_stock(self, cr, uid, ids, context=None):
        """ 1. Generate automatic picking list
            (can run more times, every time delete all previous record)
        """
        auto_move_pool = self.pool.get('stock.move.slot')
        picking_id = ids[0]

        picking = self.browse(cr, uid, picking_id, context=context)
        if picking.pick_state != 'todo':
            raise osv.except_osv(
                _('Errore'),
                _('Solo i picking da fare sono scaricabili da magazzino'),
            )

        if picking.pick_move == 'in':
            raise osv.except_osv(
                _('Errore'),
                _('Per ora è possibile solo scaricare il materiale'),
            )
        # ---------------------------------------------------------------------
        # Clean previous
        # ---------------------------------------------------------------------
        remove_line_ids = auto_move_pool.search(cr, uid, [
            ('picking_id', '=', picking_id),
        ], context=context)
        auto_move_pool.unlink(cr, uid, remove_line_ids, context=context)

        # ---------------------------------------------------------------------
        # Generate all new:
        # ---------------------------------------------------------------------
        for move in picking.move_lines:
            move_id = move.id
            product = move.product_id
            product_id = product.id
            move_quantity = move.product_uom_qty

            sequence = 0
            for cell in sorted(
                    product.product_slot_ids,
                    key=lambda x: (
                            x.slot_id.shelf_id.mode,  # auto first (manual no)
                            x.quantity,  # Large q. before
                    ), reverse=True):
                available = cell.quantity
                if move_quantity <= available:
                    quantity = move_quantity
                    move_quantity = 0.0  # covered!
                else:
                    quantity = available
                    move_quantity -= available

                # Assign auto move:
                if available > 0:
                    sequence += 1
                    auto_move_pool.create(cr, uid, {
                        'sequence': sequence,
                        'picking_id': picking_id,
                        'move_id': move_id,
                        'product_id': product_id,
                        'product_slot_id': cell.id,
                        # 'move_quantity'
                        # 'slot_quantity'
                        # 'position'
                        'quantity': quantity,
                        'real_quantity': quantity,
                        'state': 'draft',  # default
                    }, context=context)
                if move_quantity <= 0:
                    break  # move assigned all

            # Generate movement without auto stock
            if move_quantity > 0:
                _logger.error('Cannot covered move with auto stock')
                sequence += 1
                auto_move_pool.create(cr, uid, {
                    'sequence': sequence,
                    'picking_id': picking_id,
                    'move_id': move_id,
                    'product_id': product_id,
                    'product_slot_id': False,
                    'quantity': move_quantity,
                    'real_quantity': move_quantity,
                    'state': 'draft',  # default
                }, context=context)
        return True

    def generate_warehouse_move_job(self, cr, uid, ids, context=None):
        """ 2. Generate warehouse move job
        """
        product_slot_pool = self.pool.get('product.product.slot')
        picking = self.browse(cr, uid, ids, context=context)[0]

        if picking.pick_move == 'in':
            raise osv.except_osv(
                _('Errore'),
                _('Per ora è possibile solo scaricare il materiale'),
            )

        if picking.pick_state != 'todo':
            raise osv.except_osv(
                _('Errore'),
                _('Solo i picking da fare sono scaricabili da magazzino'),
            )

        # Lined of automatic shelf (no red line and manual):
        product_slot_ids = [
            line.product_slot_id.id for line in picking.warehouse_move_ids
            if line.slot_id and line.slot_id.shelf_id.mode == 'auto']
        ctx = context.copy()
        if picking.pick_move == 'out':
            ctx['force_mode'] = 'unload'
        else:
            ctx['force_mode'] = 'load'
            # TODO prepare auto assign items procedure
            # 1. Generate auto assign slot
            # 2. Create product slot
            # 3. Pass product slot with load parameters

        return product_slot_pool.open_product_slot(
            cr, uid, product_slot_ids, context=ctx)

    def confirmed_warehouse_move_job(self, cr, uid, ids, context=None):
        """ 3. Confirm execution of job
        """
        picking_id = ids[0]
        product_slot_pool = self.pool.get('product.product.slot')
        move_pool = self.pool.get('stock.move.slot')
        picking = self.browse(cr, uid, picking_id, context=context)
        if picking.pick_state != 'todo':
            raise osv.except_osv(
                _('Errore'),
                _('Solo i picking da fare sono scaricabili da magazzino'),
            )

        if picking.pick_move == 'in':
            raise osv.except_osv(
                _('Errore'),
                _('Per ora è possibile solo scaricare il materiale'),
            )
        move_ids = []
        for line in picking.warehouse_move_ids:
            if line.state != 'draft':
                _logger.error('Yet done unloaded material so do nothing!')
            product_slot = line.product_slot_id

            if product_slot:
                current_qty = product_slot.quantity
                remain_qty = line.real_quantity - current_qty
                if remain_qty < 0.0:
                    raise osv.except_osv(
                        _('Errore'),
                        _('Non più disponibile il prodotto: %s' %
                          line.product_id.default_code),
                        )
                product_slot_pool.write(cr, uid, [product_slot.id], {
                    'quantity': remain_qty,
                }, context=context)
            move_ids.append(line.id)

        # Mark as done all movement:
        return move_pool.write(cr, uid, move_ids, {
            'state': 'done',
        }, context=context)

    _columns = {
        'warehouse_move_ids': fields.one2many(
            'stock.move.slot', 'picking_id', 'Movimenti'),
    }


class ProductProduct(orm.Model):
    """ Extend product
    """
    _inherit = 'product.product'

    def open_all_product_slot(self, cr, uid, ids, context=None):
        """ Open all product slot
        """
        product_slot = self.pool.get('product.product.slot')

        product = self.browse(cr, uid, ids, context=context)[0]
        product_slot_ids = [item.id for item in product.product_slot_ids]
        return product_slot.open_product_slot(
            cr, uid, product_slot_ids, context=context)

    def get_all_warehouse_product(self, cr, uid, ids, context=None):
        """ List of all product and return result
        """
        model_pool = self.pool.get('ir.model.data')
        tree_view_id = model_pool.get_object_reference(
            cr, uid,
            'auto_warehouse', 'view_product_product_warehouse_tree')[1]
        form_view_id = False

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


class WarehouseShelfSlotRelations(orm.Model):
    """ Model name: Warehouse shelf slot rel.
    """
    _inherit = 'warehouse.shelf.slot'

    _columns = {
        'product_ids': fields.one2many(
            'product.product.slot', 'slot_id', 'Prodotti'),
    }
