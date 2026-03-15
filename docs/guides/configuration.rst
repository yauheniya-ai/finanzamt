Configuration
=============

finamt reads configuration from environment variables or a ``.env`` file
placed in the working directory.

Environment variables
---------------------

All variables use the ``FINAMT_`` prefix and can be placed in a ``.env``
file in the working directory or exported to the shell environment.

**Extraction agents (4-agent pipeline)**

.. list-table::
   :header-rows: 1
   :widths: 35 25 40

   * - Variable
     - Default
     - Description
   * - ``FINAMT_OLLAMA_BASE_URL``
     - ``http://localhost:11434``
     - Base URL of the Ollama API server.
   * - ``FINAMT_AGENT_MODEL``
     - ``qwen2.5:7b-instruct-q4_K_M``
     - Model used by all four extraction agents.
   * - ``FINAMT_AGENT_TIMEOUT``
     - ``60``
     - HTTP timeout in seconds per agent LLM call.
   * - ``FINAMT_AGENT_NUM_CTX``
     - ``4096``
     - Context window size (tokens) for agent LLM calls.
   * - ``FINAMT_AGENT_MAX_RETRIES``
     - ``2``
     - Retry attempts on failed agent LLM requests.

**OCR and PDF**

.. list-table::
   :header-rows: 1
   :widths: 35 25 40

   * - Variable
     - Default
     - Description
   * - ``FINAMT_OCR_TIMEOUT``
     - ``60``
     - Seconds to wait for PaddleOCR before falling back to Tesseract.
   * - ``FINAMT_TESSERACT_CMD``
     - ``tesseract``
     - Path to the Tesseract binary; useful when Tesseract is not on ``PATH``.
   * - ``FINAMT_PDF_DPI``
     - ``150``
     - DPI resolution used when rendering PDF pages to images.

**Data storage**

.. list-table::
   :header-rows: 1
   :widths: 35 25 40

   * - Variable
     - Default
     - Description
   * - ``FINAMT_PROJECT``
     - ``default``
     - Active project name; data is stored under ``~/.finamt/<project>/``.

``.env`` file example
---------------------

Copy ``env.example`` from the repository root and adjust it to your setup:

.. code-block:: ini

   FINAMT_OLLAMA_BASE_URL=http://localhost:11434
   FINAMT_AGENT_MODEL=qwen2.5:7b-instruct-q4_K_M
   FINAMT_AGENT_TIMEOUT=60
   FINAMT_OCR_TIMEOUT=60
   FINAMT_PROJECT=default

Programmatic configuration
---------------------------

Pass ``Config`` and / or ``AgentsConfig`` directly when constructing the agent:

.. code-block:: python

   from finamt import FinanceAgent, Config
   from finamt.agents.config import AgentsConfig

   config = Config(
       ollama_base_url="http://localhost:11434",
       ocr_timeout=90,
       pdf_dpi=200,
   )

   agents_cfg = AgentsConfig(
       agent_model="llama3.2",
       agent_timeout=90,
   )

   agent = FinanceAgent(config=config, agents_cfg=agents_cfg)

Data is stored under the named project directory by default:

.. code-block:: python

   # Use a custom project name (data stored at ~/.finamt/work/)
   agent = FinanceAgent(project="work")

   # Provide an explicit DB path
   agent = FinanceAgent(db_path="/data/myreceipts.db")

   # Disable persistence entirely
   agent = FinanceAgent(db_path=None)

Using a different model
-----------------------

Any model available in your local Ollama installation can be used.  Smaller
models are faster but may extract data less accurately:

.. code-block:: bash

   ollama pull llama3.2:3b

.. code-block:: python

   from finamt import FinanceAgent
   from finamt.agents.config import AgentsConfig

   agent = FinanceAgent(
       agents_cfg=AgentsConfig(agent_model="llama3.2:3b")
   )
