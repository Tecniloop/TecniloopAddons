Optionally sign a DeCA that is used for both administrative and contractual
purposes. The addon applies one or two sequential PAdES signatures before the
base module calculates the final PDF checksum and immutable hash-chain entry.

The active certificate and private-key paths are obtained from OCA
``l10n_es_aeat``. The signing engine is pyHanko.

Each operational company can default new drafts to administrative (unsigned) or
administrative and contractual (PAdES required). The same policy presets the
required parties and their signing companies without changing existing drafts or
issued documents.
