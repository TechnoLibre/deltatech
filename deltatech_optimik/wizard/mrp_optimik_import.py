# coding=utf-8

from odoo import models, fields, api, _
import csv
import StringIO

import base64

"""
Z|LM|991BUC ALB16 DIF
M|16363|_ALB_CORP_16_KR_0110SM_16

F|16363|450,5|781,8|1
D|368|85|||3
D|368|469,5|||1
X|0,085585

F|16363|2265,1|1463,6|2
D|768|459,5|||1
D|568|85|||1
D|568|469,5|||1
D|368|85|||53
D|399|479,5|||1
D|768|269,5|||1
D|568|269,5|||1
X|0,438136

F|16363|2497,1|2030|3
D|368|85|||70
O|16363|2457,1|1006,6|1
X|0,406196

"""


class MrpOptimikImport(models.TransientModel):
    _name = 'mrp.optimik.import'
    _description = "MRP Optimik Import"

    separator = fields.Char(default='|', size=1)
    file_name = fields.Char(string='File Name', default="Oprimik.txt")
    data_file = fields.Binary(string='File', readonly=False)

    state = fields.Selection([('choose', 'choose'),  # choose file
                              ('prepare', 'Prepare')], default='choose')

    line_import_ids = fields.One2many("mrp.optimik.import.line", 'optimik_id', string='Export lines')

    @api.multi
    def do_import(self):
        optimik_file = base64.decodestring(self.data_file)
        fp = StringIO.StringIO(optimik_file)

        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.user.company_id.id)], limit=1)

        reader = csv.reader(fp, quoting=csv.QUOTE_NONE, delimiter=self.separator.encode('ascii', 'ignore'))
        for row in reader:

            if not row:
                continue
            if row[0] == 'Z':  # determinare Job
                """
                Code = Z | Mark | Description
                """
                pass
            if row[0] == 'M':
                """
                Material:
                Code = M | Mark | Description  
                """
                product = self.env['product.product'].search([('default_code', '=', row[1])], limit=1)
                if not product:
                    raise Warning(_('Nu exista produsul %s') % row[1])

            if row[0] == 'F':
                """
                Format:
                Code = F | Cod | Length | Width | Quantity
                F|16363|450,5|781,8|1
                """
                Length = float(row[2].replace(',', '.'))
                Width = float(row[3].replace(',', '.'))
                Quantity = float(row[4].replace(',', '.'))

                self.add_line(product, Length, Width, -1 * Quantity)

            if row[0] == 'D':
                """
                Code = D | Length | Width | | | Quantity   
                """

                Length = float(row[1].replace(',', '.'))
                Width = float(row[2].replace(',', '.'))
                Quantity = float(row[5].replace(',', '.'))

                self.add_line(product, Length, Width, Quantity)

            if row[0] == 'O':
                """
                Code = O | Mark | Length | Width | Quantity   
                O|16363|2457,1|1006,6|1
                """
                Length = float(row[2].replace(',', '.'))
                Width = float(row[3].replace(',', '.'))
                Quantity = float(row[4].replace(',', '.'))

                self.add_line(product, Length, Width, Quantity)

            if row[0] == 'X':
                """
                Scrap
                """

        # de generat doua documente de miscare de stoc 1 de consum si un doc de receptie


        self.write({'state': 'prepare'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.optimik.import',
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'new',
        }

    def add_line(self, product, Length, Width, Quantity):

        uom_square_meter = self.env.ref('product.product_uom_square_meter')
        dimension = "%s x %s" % (Length, Width)
        factor = float(Length) * float(Width) / (1000.0 * 1000.0)
        uom = self.env['product.uom'].search([('name', '=', dimension),
                                              ('category_id', '=', uom_square_meter.category_id.id)], limit=1)

        if not uom:
            uom = self.env['product.uom'].create({'name': dimension,
                                                  'category_id': uom_square_meter.category_id.id,
                                                  'uom_type': 'bigger', 'factor': 1 / factor})

        self.env["mrp.optimik.import.line"].create({
            'optimik_id': self.id,
            'product_id': product.id,
            'quantity': Quantity,
            'uom_id': uom.id
        })

    @api.multi
    def do_transfer(self):
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.user.company_id.id)], limit=1)

        picking_type_consume = self.env.ref('stock.picking_type_consume')
        picking_type_receipt_production = self.env.ref('stock.picking_type_receipt_production')

        context = {'default_picking_type_id': picking_type_receipt_production.id}
        picking_in = self.env['stock.picking'].with_context(context).create(
            {'picking_type_id': picking_type_receipt_production.id})

        context = {'default_picking_type_id': picking_type_consume.id}
        picking_out = self.env['stock.picking'].with_context(context).create(
            {'picking_type_id': picking_type_consume.id})

        for line in self.line_import_ids:

            if line.quantity > 0:
                picking = picking_in
                quantity = line.quantity
            else:
                picking = picking_out
                quantity = -1 * line.quantity

            values = {
                'state': 'assigned',
                'product_id': line.product_id.id,
                'product_uom': line.uom_id.id,
                'product_uom_qty': quantity,
                'name': line.product_id.name,
                'picking_id': picking.id,
                'location_id': picking.picking_type_id.default_location_src_id.id,
                'location_dest_id': picking.picking_type_id.default_location_dest_id.id
            }

            move = self.env['stock.move'].create(values)

            values = {
                'state': 'assigned',
                'picking_id': picking.id,
                'product_id': line.product_id.id,
                'product_uom_id': line.uom_id.id,
                'product_qty': quantity,
                'ordered_qty': quantity,
                'qty_done': quantity,
                'location_id': picking.picking_type_id.default_location_src_id.id,
                'location_dest_id': picking.picking_type_id.default_location_dest_id.id,
                # 'linked_move_operation_ids': [6, 0, [move.id]]
            }

            operation = self.env['stock.pack.operation'].create(values)

            self.env['stock.move.operation.link'].create({
                'operation_id': operation.id,
                'move_id': move.id
            })

        return {
            'domain': [('id', 'in', [picking_in.id, picking_out.id])],
            'name': _('Pickings'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'stock.picking',
            'view_id': False,
            'context': {},
            'type': 'ir.actions.act_window'
        }


class MrpOptimikImportLine(models.TransientModel):
    _name = "mrp.optimik.import.line"

    optimik_id = fields.Many2one('mrp.optimik.import', string="Optimik")
    product_id = fields.Many2one('product.product')

    quantity = fields.Float(string="Qty")
    uom_id = fields.Many2one('product.uom', 'Unit of Measure')