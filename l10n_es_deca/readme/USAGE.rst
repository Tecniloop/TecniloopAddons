#. Open an eligible stock transfer and select **Create / open DeCA**.  Alternatively,
   use **Create DeCA documents** on a batch to create one draft per picking.
#. Review all stock-prefilled values.  They are suggestions, not legal assertions.
#. Complete the effective carrier, vehicle and other mandatory data.
#. Issue and seal the PDF before the road transport starts.
#. Record delivery of the current PDF or QR to the driver.
#. Start the DeCA workflow.  If data change, create a traced revision and deliver
   the new version.
#. Complete the DeCA when the service ends.

For a PDF that is also used contractually, install ``l10n_es_deca_ades`` before
selecting **Administrative and contractual**. The base addon deliberately refuses
to issue that modality unsigned.

Enable **DeCA required** on a transfer to prevent its validation until the current
sealed version has delivery evidence.
