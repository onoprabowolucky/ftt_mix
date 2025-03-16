import os
import time
import json
import logging
from typing import Dict, Any, Optional, List

from web3 import Web3
from web3.contract import Contract
from web3.types import LogReceipt
from dotenv import load_dotenv
from requests.exceptions import RequestException

# --- Basic Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
)


class ConfigLoader:
    """
    A dedicated class to load and validate configuration from environment variables.
    This promotes separation of concerns and makes configuration management cleaner.
    """

    def __init__(self, dotenv_path: str = '.env'):
        """
        Initializes the ConfigLoader and loads environment variables from the specified path.

        Args:
            dotenv_path (str): The path to the .env file.
        """
        load_dotenv(dotenv_path)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"Loading configuration from {dotenv_path}")

    def load_config(self) -> Dict[str, Any]:
        """
        Loads required configuration keys from the environment and validates them.

        Returns:
            Dict[str, Any]: A dictionary containing the configuration parameters.

        Raises:
            ValueError: If a required environment variable is not set.
        """
        required_keys = [
            'SOURCE_CHAIN_RPC_URL',
            'DESTINATION_CHAIN_RPC_URL',
            'SOURCE_BRIDGE_CONTRACT_ADDRESS',
            'DESTINATION_BRIDGE_CONTRACT_ADDRESS',
            'RELAYER_PRIVATE_KEY',
            'BLOCK_PROCESSING_INTERVAL_SECONDS',
            'CONFIRMATION_BLOCKS'
        ]
        config = {}
        for key in required_keys:
            value = os.getenv(key)
            if not value:
                self.logger.error(f"Missing required environment variable: {key}")
                raise ValueError(f"Configuration Error: Missing environment variable '{key}'")
            config[key] = value

        # Type conversions for specific keys
        config['BLOCK_PROCESSING_INTERVAL_SECONDS'] = int(config['BLOCK_PROCESSING_INTERVAL_SECONDS'])
        config['CONFIRMATION_BLOCKS'] = int(config['CONFIRMATION_BLOCKS'])

        self.logger.info("Configuration loaded and validated successfully.")
        return config


class BlockchainConnector:
    """
    Manages the connection to a blockchain node via Web3.py.
    Handles connection retries and provides a stable Web3 instance.
    """

    def __init__(self, rpc_url: str, chain_name: str):
        """
        Initializes the connector.

        Args:
            rpc_url (str): The HTTP RPC endpoint URL for the blockchain node.
            chain_name (str): A friendly name for the chain (e.g., 'SourceChain').
        """
        self.rpc_url = rpc_url
        self.chain_name = chain_name
        self.web3: Optional[Web3] = None
        self.logger = logging.getLogger(f"{self.__class__.__name__}.{self.chain_name}")
        self.connect()

    def connect(self):
        """
        Establishes a connection to the blockchain node.
        Includes a basic check to ensure the connection is live.
        """
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.web3.is_connected():
                raise ConnectionError("Failed to connect to the node.")
            self.logger.info(f"Successfully connected to {self.chain_name} at {self.rpc_url}.")
            self.logger.info(f"Chain ID: {self.web3.eth.chain_id}, Current Block: {self.web3.eth.block_number}")
        except (RequestException, ConnectionError) as e:
            self.logger.error(f"Could not connect to {self.chain_name}: {e}")
            self.web3 = None
            # In a real-world application, you would implement a retry mechanism here.
            raise

    def get_contract(self, address: str, abi: List[Dict]) -> Optional[Contract]:
        """
        Returns a Web3 contract instance.

        Args:
            address (str): The contract's address.
            abi (List[Dict]): The contract's ABI.

        Returns:
            Optional[Contract]: A Web3 contract instance, or None if not connected.
        """
        if not self.web3:
            self.logger.warning("Cannot get contract, not connected to the blockchain.")
            return None
        checksum_address = self.web3.to_checksum_address(address)
        return self.web3.eth.contract(address=checksum_address, abi=abi)


class EventScanner:
    """
    Scans a given blockchain for specific events from a smart contract.
    Maintains state about the last block scanned to ensure continuous operation.
    """

    def __init__(self, connector: BlockchainConnector, contract: Contract, event_name: str, state_file: str = 'scanner_state.json'):
        """
        Initializes the EventScanner.

        Args:
            connector (BlockchainConnector): The connector for the blockchain to scan.
            contract (Contract): The Web3 contract instance to monitor.
            event_name (str): The name of the event to listen for.
            state_file (str): Path to the file for persisting the last scanned block.
        """
        self.connector = connector
        self.contract = contract
        self.event_name = event_name
        self.state_file = state_file
        self.logger = logging.getLogger(self.__class__.__name__)
        self.last_scanned_block = self._load_state()

    def _load_state(self) -> int:
        """
        Loads the last scanned block number from the state file.
        If the file doesn't exist, it starts from the current block.
        """
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    last_block = state.get('last_scanned_block', 0)
                    self.logger.info(f"Loaded last scanned block from state: {last_block}")
                    return last_block
        except (IOError, json.JSONDecodeError) as e:
            self.logger.warning(f"Could not load state file: {e}. Starting from current block.")

        # Fallback to current block number if state loading fails
        if self.connector.web3:
            current_block = self.connector.web3.eth.block_number
            self.logger.info(f"No valid state file found. Starting scan from current block: {current_block}")
            return current_block
        return 0

    def _save_state(self):
        """
        Saves the last scanned block number to the state file.
        """
        try:
            with open(self.state_file, 'w') as f:
                json.dump({'last_scanned_block': self.last_scanned_block}, f)
        except IOError as e:
            self.logger.error(f"Fatal: Could not save state to {self.state_file}: {e}")

    def scan_for_events(self, confirmation_blocks: int) -> List[LogReceipt]:
        """
        Scans a range of blocks for the target event.

        Args:
            confirmation_blocks (int): Number of blocks to wait for to avoid re-orgs.

        Returns:
            List[LogReceipt]: A list of found event logs.
        """
        if not self.connector.web3:
            self.logger.error("Cannot scan events, blockchain not connected.")
            return []

        try:
            latest_block = self.connector.web3.eth.block_number
            # We scan up to `latest_block - confirmation_blocks` to mitigate re-org risk
            to_block = latest_block - confirmation_blocks
            from_block = self.last_scanned_block + 1

            if from_block > to_block:
                self.logger.info(f"Waiting for new blocks. Current: {latest_block}, Scanning up to: {to_block}, Last scanned: {self.last_scanned_block}")
                return []

            self.logger.info(f"Scanning for '{self.event_name}' events from block {from_block} to {to_block}.")

            event_filter = self.contract.events[self.event_name].create_filter(
                fromBlock=from_block,
                toBlock=to_block
            )
            events = event_filter.get_all_entries()

            if events:
                self.logger.info(f"Found {len(events)} new '{self.event_name}' event(s).")

            # Update state and save it
            self.last_scanned_block = to_block
            self._save_state()

            return events
        except Exception as e:
            # This could be a node error, RPC timeout, etc.
            self.logger.error(f"An error occurred during event scanning: {e}")
            return []


class TransactionRelayer:
    """
    Simulates the process of relaying a transaction to the destination chain.
    In a real system, this would sign and broadcast a transaction.
    Here, it constructs, signs, and logs the transaction for demonstration.
    """

    def __init__(self, connector: BlockchainConnector, contract: Contract, private_key: str):
        """
        Initializes the TransactionRelayer.

        Args:
            connector (BlockchainConnector): The connector for the destination blockchain.
            contract (Contract): The Web3 destination contract instance.
            private_key (str): The private key of the relayer's wallet.
        """
        if not connector.web3:
            raise ValueError("Relayer's blockchain connector is not initialized.")
        self.connector = connector
        self.contract = contract
        self.web3 = connector.web3
        self.account = self.web3.eth.account.from_key(private_key)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"Relayer initialized with address: {self.account.address}")

    def simulate_claim_withdrawal(self, event_data: Dict[str, Any]):
        """
        Constructs and signs a 'claimWithdrawal' transaction based on event data.

        Args:
            event_data (Dict[str, Any]): The parsed data from the source chain event.
        """
        try:
            self.logger.info(f"Preparing to relay claim for user {event_data['user']} for amount {event_data['amount']}.")

            # Build the transaction
            nonce = self.web3.eth.get_transaction_count(self.account.address)
            tx_params = {
                'from': self.account.address,
                'nonce': nonce,
                # In a real scenario, you'd use web3.eth.gas_price or EIP-1559 fields
                'gas': 200000, # A sensible default for simulation
                'gasPrice': self.web3.to_wei('50', 'gwei')
            }

            # Call the 'claimWithdrawal' function on the destination contract
            claim_tx = self.contract.functions.claimWithdrawal(
                event_data['user'],
                event_data['amount'],
                event_data['sourceTxHash']
            ).build_transaction(tx_params)

            # Sign the transaction
            signed_tx = self.web3.eth.account.sign_transaction(claim_tx, self.account.key)

            self.logger.info(f"Successfully signed transaction to claim withdrawal.")
            self.logger.info(f"  - TX Hash (simulated): {signed_tx.hash.hex()}")
            self.logger.info(f"  - Raw TX (simulated): {signed_tx.rawTransaction.hex()}")
            # In a real system, the next line would be:
            # tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # self.logger.info(f"Transaction broadcasted with hash: {tx_hash.hex()}")

        except Exception as e:
            self.logger.error(f"Failed to simulate and sign withdrawal claim: {e}")


class BridgeListener:
    """
    The main orchestrator class that ties all components together.
    It runs the main loop to listen for events and trigger the relay process.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the entire bridge listening service.
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

        # --- Define ABIs (in a real project, these would be in separate files) ---
        self.source_bridge_abi = json.loads('''
        [
            {
                "anonymous": false,
                "inputs": [
                    {"indexed": true, "name": "user", "type": "address"},
                    {"indexed": false, "name": "amount", "type": "uint256"}
                ],
                "name": "DepositInitiated",
                "type": "event"
            }
        ]
        ''')
        self.destination_bridge_abi = json.loads('''
        [
            {
                "inputs": [
                    {"name": "user", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "sourceTxHash", "type": "bytes32"}
                ],
                "name": "claimWithdrawal",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]
        ''')

        # --- Initialize components ---
        self.source_connector = BlockchainConnector(config['SOURCE_CHAIN_RPC_URL'], 'SourceChain')
        self.destination_connector = BlockchainConnector(config['DESTINATION_CHAIN_RPC_URL'], 'DestinationChain')

        source_contract = self.source_connector.get_contract(config['SOURCE_BRIDGE_CONTRACT_ADDRESS'], self.source_bridge_abi)
        destination_contract = self.destination_connector.get_contract(config['DESTINATION_BRIDGE_CONTRACT_ADDRESS'], self.destination_bridge_abi)

        if not source_contract or not destination_contract:
            raise RuntimeError("Failed to initialize smart contracts. Check addresses and ABIs.")

        self.scanner = EventScanner(self.source_connector, source_contract, 'DepositInitiated')
        self.relayer = TransactionRelayer(self.destination_connector, destination_contract, config['RELAYER_PRIVATE_KEY'])

    def process_event(self, event: LogReceipt):
        """
        Processes a single event log and triggers the relayer.
        """
        try:
            user = event['args']['user']
            amount = event['args']['amount']
            tx_hash = event['transactionHash']

            self.logger.info(f"Processing event from tx {tx_hash.hex()}: User {user} deposited {amount / 1e18} tokens.")

            event_data = {
                'user': user,
                'amount': amount,
                'sourceTxHash': tx_hash
            }

            # Trigger the relaying process
            self.relayer.simulate_claim_withdrawal(event_data)

        except KeyError as e:
            self.logger.error(f"Event log is missing expected argument: {e}. Log: {event}")
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during event processing: {e}")

    def run(self):
        """
        Starts the main listening loop.
        """
        self.logger.info("Bridge Listener starting up...")
        while True:
            try:
                events = self.scanner.scan_for_events(self.config['CONFIRMATION_BLOCKS'])
                if events:
                    for event in events:
                        self.process_event(event)
                else:
                    self.logger.info("No new events found. Waiting for next cycle.")

                interval = self.config['BLOCK_PROCESSING_INTERVAL_SECONDS']
                self.logger.info(f"Sleeping for {interval} seconds...")
                time.sleep(interval)

            except KeyboardInterrupt:
                self.logger.info("Shutdown signal received. Exiting...")
                break
            except Exception as e:
                self.logger.critical(f"A critical error occurred in the main loop: {e}. Restarting loop after a delay.")
                time.sleep(60) # Wait a minute before retrying on critical failure


if __name__ == '__main__':
    try:
        config_loader = ConfigLoader()
        app_config = config_loader.load_config()
        listener = BridgeListener(app_config)
        listener.run()
    except (ValueError, RuntimeError, ConnectionError) as e:
        logging.critical(f"Application failed to start: {e}")
