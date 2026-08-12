#. Create the DeCA from a transfer or batch. The operational company's defaults
   determine whether the new draft is administrative (unsigned) or contractual
   (PAdES required).
#. While it is a draft, review or change the purpose, required parties and signing
   companies. Explicit values on the draft take precedence over company defaults.
#. For contractual use, ensure the contractual shipper and effective carrier match
   the commercial partners of their respective signing companies.
#. Issue the DeCA as an authorized PAdES signer.
#. Independently validate the resulting PDF against the applicable trust,
   revocation, certificate-policy and representation requirements.

Every traced revision is rendered and signed again. Previous signed versions remain
immutable.

Changing company defaults affects only DeCA drafts created afterwards. It never
rewrites an existing draft or a sealed version.
