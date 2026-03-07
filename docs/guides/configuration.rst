Configuration
=============

finamt reads configuration from environment variables or a ``.env`` file
placed in the working directory.

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Variable
     - Default
     - Description
   * - ``OLLAMA_BASE_URL``
     - ``http://localhost:11434``
     - Base URL of the Ollama API server.
   * - ``OLLAMA_MODEL``
     - ``qwen2.5:7b-instruct-q4_K_M``
     - Default model used for all extraction agents.
   * - ``OLLAMA_TIMEOUT``
     - ``120``
     - HTTP timeout in seconds for Ollama requests.
   * - ``DB_PATH``
     - ``finamt.db``
     - Path to the SQLite database file.
   * - ``OCR_ENGINE``
     - ``paddle``
     - Primary OCR engine (``paddle`` or ``tesseract``).
   * - ``OCR_TIMEOUT``
     - ``60``
     - Timeout in seconds for a single OCR pass.

``.env`` file example
---------------------

Copy ``env.example`` from the repository and adjust it to your setup:

.. code-block:: ini

   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
   OLLAMA_TIMEOUT=120
   DB_PATH=./data/finamt.db
   OCR_ENGINE=paddle
   OCR_TIMEOUT=60

Programmatic configuration
---------------------------

You can also pass configuration directly when constructing the agent:

.. code-block:: python

   from finamt import FinanceAgent, Config, ModelConfig

   config = Config(
       model=ModelConfig(
           base_url="http://localhost:11434",
           model_name="llama3.2:3b",
           timeout=60,
       ),
       db_path="./receipts.db",
   )

   agent = FinanceAgent(config=config)

Using a different model
-----------------------

Any model available in your local Ollama installation can be used.  Smaller
models are faster but may extract data less accurately:

.. code-block:: bash

   ollama pull llama3.2:3b

.. code-block:: python

   from finamt import FinanceAgent, Config, ModelConfig

   agent = FinanceAgent(
       config=Config(model=ModelConfig(model_name="llama3.2:3b"))
   )
