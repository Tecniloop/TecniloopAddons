Known limitations
~~~~~~~~~~~~~~~~~

* The addon cannot determine whether a transport is legally in scope or exempt.
* It cannot prove TLS policy, external availability, trusted time, backup
  immutability or factual correctness of operator-entered data.
* It deliberately does not aggregate a whole batch into one DeCA because a batch
  can contain several destinations and transport services.
* The administrative DeCA does not require a signature. The base addon therefore
  refuses to issue the contractual modality without an installed signing addon.

Planned
~~~~~~~

* Add optional glue modules for OCA carrier, fleet and e-CMR projects once their
  Odoo 19 target APIs are agreed.
* Extend ``l10n_es_deca_ades`` with remote counterparty,
  qualified-trust-service and HSM signing adapters.
* Add optional SMS, WhatsApp or mobile-app delivery adapters without making them
  a statutory validity condition.
* Evaluate automated domestic-scope suggestions without replacing the operator's
  legal applicability decision.
