* Install and configure an active, in-date AEAT certificate for every Odoo company
  that will sign.
* Run Odoo 19 on Python 3.12 or newer and install ``pyHanko==0.24.*``. This is the
  compatible series for Odoo's official Python 3.12 pin
  ``cryptography==42.0.8``. The addon fails closed for other combinations.
* On Python 3.10/3.11, use a separate signing service: Odoo pins
  ``cryptography==3.4.8`` there, which is incompatible with pyHanko 0.24.
* Grant **DeCA PAdES Signer** only to users authorized to invoke those company keys.
* Choose PAdES B-B or PAdES B-T in Settings. B-T requires an HTTPS RFC 3161
  timestamp authority URL.
* In **Settings > DeCA PAdES**, choose **Default DeCA purpose** per operational
  company:

  * **Administrative only (no signature)** creates unsigned DeCA drafts.
  * **Administrative and contractual (PAdES required)** creates drafts that cannot
    be issued until the configured PAdES signatures have been embedded.

* For the contractual default, select the default parties (shipper, carrier or
  both) and the Odoo signing company for each role. These are initial values copied
  to new drafts. They do not update existing drafts and remain editable until the
  document is issued.
* Ensure every signing company commercial partner is the same partner selected as
  contractual shipper or effective carrier on the DeCA.
* Establish and audit the organizational authority, exclusive key-control and
  representation procedures required by the intended AdES/QES policy.
