import inspect
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import DepositWalletCall

print("=== execute_deposit_wallet_batch ===")
print(inspect.getsource(RelayClient.execute_deposit_wallet_batch))

print("\n=== DepositWalletCall ===")
try:
    print(inspect.getsource(DepositWalletCall))
except:
    print(DepositWalletCall)

print("\n=== deploy_deposit_wallet ===")
print(inspect.getsource(RelayClient.deploy_deposit_wallet)[:1500])
