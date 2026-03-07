Quickstart
==========

Process a single receipt
------------------------

.. code-block:: python

   from finamt import FinanceAgent

   agent = FinanceAgent()
   result = agent.process_receipt("invoice.pdf")

   if result.success:
       data = result.data
       print(f"Vendor : {data.counterparty_name}")
       print(f"Date   : {data.document_date}")
       print(f"Total  : {data.total_amount} {data.currency}")
       print(f"VAT    : {data.vat_amount} ({data.vat_rate}%)")
   else:
       print(f"Error: {result.error_message}")

Process an image file
---------------------

The library accepts PDF and common image formats (JPEG, PNG, TIFF):

.. code-block:: python

   result = agent.process_receipt("scan.jpg")

Batch processing
----------------

.. code-block:: python

   import glob
   from finamt import FinanceAgent

   agent = FinanceAgent()

   for path in glob.glob("receipts/*.pdf"):
       result = agent.process_receipt(path)
       if result.success:
           print(f"{path}: {result.data.total_amount}")
       else:
           print(f"{path}: FAILED — {result.error_message}")

Web UI
------

Start the local web interface:

.. code-block:: bash

   finamt --ui

Then open ``http://localhost:8000`` in your browser.  The UI lets you upload
receipts, review and edit extracted data, manage counterparties, and export
reports.

Command-line interface
----------------------

.. code-block:: bash

   # Process a single file and print JSON output
   finamt process invoice.pdf

   # Show help
   finamt --help
