#!/usr/bin/env python3
"""
Simple test script for getProposals() - no private key needed.
Just tests the read-only proposal fetching.
"""
import os

# Set a public RPC if not configured (or use your own)
if not os.getenv('SIPHON_RPC_L2'):
    # Public Arbitrum RPC - may be rate limited
    os.environ['SIPHON_RPC_L2'] = 'https://arb1.arbitrum.io/rpc'

# Now import (State.py will use the env var)
from lib import Contract

print("Testing getProposals()...\n")

proposals = Contract.getProposals()

if proposals:
    print(f"\nFound {len(proposals)} active proposal(s):\n")
    for p in proposals:
        print(f"  ID: {p['proposalId']}")
        print(f"  Title: {p['title']}")
        print(f"  Proposer: {p['proposer']}")
        print(f"  Vote Start: {p['voteStart']}")
        print(f"  Vote End: {p['voteEnd']}")
        print()
else:
    print("\nNo active proposals found.")
