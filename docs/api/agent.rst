Agent
=====

The :class:`~finamt.FinanceAgent` is the main entry point for processing
receipts. Internally it runs a 4-agent pipeline:

1. **Metadata agent** — receipt date, number, type, category
2. **Counterparty agent** — vendor / client name, address, VAT ID, tax number
3. **Amounts agent** — total, VAT amount, VAT rate, net amount, currency
4. **Line items agent** — individual purchased items with per-item VAT

finamt.agents.agent
----------------------

.. automodule:: finamt.agents.agent
   :members:
   :undoc-members:
   :show-inheritance:

finamt.agents.config
-----------------------

.. automodule:: finamt.agents.config
   :members:
   :undoc-members:
   :show-inheritance:

finamt.agents.pipeline
-------------------------

.. automodule:: finamt.agents.pipeline
   :members:
   :undoc-members:
   :show-inheritance:

finamt.agents.prompts
------------------------

.. automodule:: finamt.agents.prompts
   :members:
   :undoc-members:
   :show-inheritance:

finamt.agents.llm\_caller
-----------------------------

.. automodule:: finamt.agents.llm_caller
   :members:
   :undoc-members:
   :show-inheritance:
