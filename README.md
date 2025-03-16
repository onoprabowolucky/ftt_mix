# ftt_mix: Cross-Chain Bridge Event Listener Simulation

This repository contains a Python-based simulation of a cross-chain bridge event listener. It is designed as an architectural showcase, demonstrating how a critical off-chain component of a decentralized system might be structured. The script listens for `DepositInitiated` events on a source blockchain, processes them, and then simulates the creation and signing of a corresponding `claimWithdrawal` transaction on a destination blockchain.

This is not a production-ready relayer but a comprehensive model intended for educational and architectural review purposes.

## Concept

Cross-chain bridges are essential for blockchain interoperability, allowing users to move assets from one chain to another. A common architecture involves:
1.  **Source Chain**: A user deposits assets into a bridge smart contract, which locks the assets and emits an event (e.g., `DepositInitiated`).
2.  **Off-Chain Relayer/Listener**: A trusted service (or a network of services) constantly monitors the source chain for these deposit events.
3.  **Destination Chain**: Upon detecting a valid event, the relayer submits a transaction to a bridge contract on the destination chain to mint a corresponding amount of wrapped assets for the user.

This project simulates the **Off-Chain Relayer/Listener** component. It connects to two blockchain RPC endpoints, scans for events, and prepares transactions for the destination chain.

## Code Architecture

The script is designed with a clear separation of concerns, using multiple classes to handle distinct responsibilities.

```
+-------------------+      +-----------------------+
|   ConfigLoader    |----->|     BridgeListener    |<---- (Orchestrator)
+-------------------+      | (Main Application)    |
                           +-----------+-----------+
                                       |
                  +--------------------+--------------------+
                  |                                         |
                  v                                         v
+------------------------+                     +----------------------+
|     EventScanner       |                     |  TransactionRelayer  |
+------------------------+                     +----------------------+
| - Scans for events on  |                     | - Simulates tx on    |
|   the source chain     |                     |   destination chain  |
| - Manages scan state   |                     | - Signs transaction  |
+-----------+------------+                     +----------+-----------+
            |                                              |
            v                                              v
+------------------------+                     +------------------------+
|  BlockchainConnector   |                     |  BlockchainConnector   |
|  (Source Chain)        |                     |  (Destination Chain)   |
+------------------------+                     +------------------------+
| - Manages Web3 conn.   |                     | - Manages Web3 conn.   |
| - Provides contract obj|                     | - Provides contract obj|
+------------------------+                     +------------------------+

```

*   **`ConfigLoader`**: Safely loads and validates required configuration (RPC URLs, private keys, etc.) from a `.env` file. This prevents hardcoding sensitive information.
*   **`BlockchainConnector`**: A reusable class that manages the `web3.py` connection to a specific blockchain node. It handles the initial connection and provides a simple interface to get contract instances.
*   **`EventScanner`**: The core component for the source chain. It periodically scans block ranges for a specific event. To ensure robustness, it persists its state (the last block it scanned) to a local JSON file (`scanner_state.json`), allowing it to resume where it left off after a restart. It also uses a confirmation block delay to mitigate the risk of processing events from blockchain re-organizations.
*   **`TransactionRelayer`**: The core component for the destination chain. It takes processed event data, constructs a corresponding transaction (e.g., `claimWithdrawal`), signs it with the relayer's private key, and logs the result. In this simulation, it does not broadcast the transaction to save gas and complexity.
*   **`BridgeListener`**: The main orchestrator. It initializes all other components, contains the primary application loop, and coordinates the flow of data from the `EventScanner` to the `TransactionRelayer`.

## How it Works

The listener operates in a continuous loop with the following steps:

1.  **Initialization**: On startup, the `ConfigLoader` reads the `.env` file. The `BridgeListener` then creates `BlockchainConnector` instances for both the source and destination chains.
2.  **State Loading**: The `EventScanner` loads its last processed block number from `scanner_state.json`. If the file doesn't exist, it defaults to the current block number of the source chain.
3.  **Scanning**: In each loop iteration, the `EventScanner` determines the block range to scan. It queries the source chain's RPC for `DepositInitiated` events between `last_scanned_block + 1` and `current_block - confirmation_blocks`.
4.  **Event Processing**: If any events are found, the `BridgeListener` iterates through them.
5.  **Data Extraction**: For each event, it extracts the relevant data (e.g., the user's address, the deposit amount, and the source transaction hash).
6.  **Transaction Simulation**: The extracted data is passed to the `TransactionRelayer`. The relayer builds a `claimWithdrawal` transaction, sets the nonce and gas parameters, and signs it using the relayer's private key.
7.  **Logging**: The signed raw transaction and its simulated hash are logged to the console. **No transaction is actually sent.**
8.  **State Update**: The `EventScanner` updates its `last_scanned_block` and saves it to the state file.
9.  **Wait**: The application pauses for a configurable interval (`BLOCK_PROCESSING_INTERVAL_SECONDS`) before starting the next scanning cycle.

## Usage Example

### 1. Setup Environment

First, clone the repository:
```bash
git clone https://github.com/your-username/ftt_mix.git
cd ftt_mix
```

Create a Python virtual environment and install the required dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
pip install -r requirements.txt
```

### 2. Create Configuration File

Create a file named `.env` in the root of the project directory. This file will hold your configuration and secrets. Populate it with the following content, replacing the placeholder values.

*For a practical test, you can use a public Ethereum RPC and the Wrapped Ether (WETH) contract, as its `Deposit` event has a similar structure to our simulated event.*

```dotenv
# --- Source Chain (e.g., Ethereum Mainnet) ---
# Get a free RPC URL from a provider like Infura or Alchemy
SOURCE_CHAIN_RPC_URL="https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID"
# WETH contract address on Ethereum, which has a `Deposit` event
# We will pretend its `Deposit(address indexed dst, uint wad)` event is our `DepositInitiated`
SOURCE_BRIDGE_CONTRACT_ADDRESS="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

# --- Destination Chain (e.g., Polygon) ---
DESTINATION_CHAIN_RPC_URL="https://polygon-rpc.com/"
# A placeholder address for the destination contract
DESTINATION_BRIDGE_CONTRACT_ADDRESS="0x1234567890123456789012345678901234567890"

# --- Relayer Configuration ---
# IMPORTANT: Use a burner private key with NO real funds for this simulation.
RELAYER_PRIVATE_KEY="0xYOUR_BURNER_PRIVATE_KEY_WITHOUT_FUNDS"

# --- Listener Configuration ---
# How often the script should scan for new blocks (in seconds)
BLOCK_PROCESSING_INTERVAL_SECONDS=30
# Number of blocks to wait before processing an event to avoid re-orgs
CONFIRMATION_BLOCKS=12
```

**Note**: The ABIs in the script are simplified for this simulation. The source ABI for `DepositInitiated(address, uint256)` is compatible with the WETH `Deposit(address, uint256)` event signature, which is why it can be used for a live demo.

### 3. Run the Script

Execute the main script from your terminal:
```bash
python script.py
```

### 4. Expected Output

The script will start logging its activities. When it finds a new event on the source contract, you will see output similar to this:

```
2023-10-27 15:30:00,123 - INFO - [BridgeListener] - Bridge Listener starting up...
2023-10-27 15:30:05,456 - INFO - [EventScanner] - Scanning for 'DepositInitiated' events from block 18450001 to 18450050.
2023-10-27 15:30:08,789 - INFO - [EventScanner] - Found 1 new 'DepositInitiated' event(s).
2023-10-27 15:30:08,790 - INFO - [BridgeListener] - Processing event from tx 0x...: User 0x... deposited 0.5 tokens.
2023-10-27 15:30:08,791 - INFO - [TransactionRelayer] - Preparing to relay claim for user 0x... for amount 500000000000000000.
2023-10-27 15:30:09,999 - INFO - [TransactionRelayer] - Successfully signed transaction to claim withdrawal.
2023-10-27 15:30:10,000 - INFO - [TransactionRelayer] -   - TX Hash (simulated): 0x...
2023-10-27 15:30:10,001 - INFO - [TransactionRelayer] -   - Raw TX (simulated): 0x...
2023-10-27 15:30:35,000 - INFO - [BridgeListener] - Sleeping for 30 seconds...
```
