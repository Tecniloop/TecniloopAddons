Issue the Spanish electronic administrative transport control document (DeCA)
from Odoo 19 Community stock transfers.  Each document seals a canonical Spanish
PDF with a QR that resolves directly to the same PDF without login or intermediate
interaction.

One DeCA is linked to one ``stock.picking``.  When documents are created from a
``stock.picking.batch``, the module creates one per picking and freezes the batch
reference as provenance.  This avoids presenting a multidestination batch as a
single transport service.

The base addon is deliberately administrative and does not sign PDFs. Install
``l10n_es_deca_ades`` only when the same document is also used contractually and
the selected parties must sign it with PAdES.
