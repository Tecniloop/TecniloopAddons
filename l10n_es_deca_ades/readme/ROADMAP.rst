Known limitations
~~~~~~~~~~~~~~~~~

* An AEAT/SII certificate is reusable key material, but its presence does not by
  itself prove AdES or QES qualification, representation authority or a second
  party's consent.
* The addon signs only for parties represented by Odoo companies with locally
  configured AEAT certificate material.
* Remote counterparties, HSMs, qualified remote-signature services and EUTL
  validation require separate adapters.

Planned
~~~~~~~

* Add interrupted-signing adapters for remote qualified trust services and external
  counterparties.
* Add HSM/PKCS#11 and cloud-KMS signers without exposing private keys to Odoo workers.
* Add independent EUTL, revocation and long-term PAdES validation policies.
