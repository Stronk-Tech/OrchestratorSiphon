# All logic related to direct interaction with the user
# Like asking the user for a password or voting on a proposal
# Import our own libraries
from lib import State, Contract


### Main logic for user handling


"""
@brief Print all user choices
"""
def printOptions(options):
    print("\nPlease choose an option:")
    for option in options:
        print(option)
    print()

"""
@brief Asks the user to give us a number
@return -1 on failure, else an integer
"""
def getInputAsInt():
    choice = input("Enter a number: ")
    
    try:
        choice = int(choice)
    except ValueError:
        print("Invalid input. Please enter a valid number.\n")
        choice = -1
    return choice

"""
@brief Asks the user for keystore passwords or choose from an option menu
"""
def handleUserInput():
    # Else continue to menu
    while True:
        options = [
            "1. Treasury proposals",
            "2. Governance proposals (LIP)",
            "3. Set commission rates"
        ]
        if not State.LOCK_INTERACTIVE:
            options.append("0. Start siphoning. Press `CTRL + z`or `CTRL + \\` if you want to switch back to interactive mode")
        printOptions(options)
        choice = getInputAsInt()

        if choice == 0 and not State.LOCK_INTERACTIVE:
            print("Siphoning... 💸")
            State.require_user_input = False
            break
        elif choice == -1:
            continue
        else:
            if choice == 1:
                handleTreasury()
            elif choice == 2:
                handleGovernance()
            elif choice == 3:
                handleCommissionRates()
            else:
                print("UNIMPL: chose {0}".format(choice))
    

### Commission rates


"""
@brief Handler for setting commission rates
"""
def handleCommissionRates():
    while True:
        options = []
        for orchIdx in range(len(State.orchestrators)):
            options.append("{0}. Set rates for {1}".format(orchIdx + 1, State.orchestrators[orchIdx].source_address))
        options.append("0. Back to menu")
        printOptions(options)
        choice = getInputAsInt()

        if choice == 0:
            return
        elif choice == -1:
            continue
        else:
            orchIdx = choice - 1
            if orchIdx < len(State.orchestrators):
                handleSetRates(orchIdx)
            else:
                print("UNIMPL: chose {0}".format(choice))

"""
@brief Parse percentage input handling different decimal separators
@param input_str: string input from user
@return: float value of the percentage
"""
def parsePercentage(input_str):
    # Remove any whitespace
    input_str = input_str.strip()

    # Handle common percentage formats for 0-100 range
    # European: 11,5 -> 11.5
    # US: 11.5 -> 11.5
    # Handle cases like "10,50" or "10.50"

    # If there's both comma and dot, it's likely thousands separator + decimal
    # But since we're dealing with 0-100%, this shouldn't happen in valid input
    if ',' in input_str and '.' in input_str:
        raise ValueError("Ambiguous number format")

    # Simple case: replace comma with dot for European decimal separator
    if ',' in input_str:
        input_str = input_str.replace(',', '.')

    return float(input_str)

"""
@brief Handler for setting rates for a specific orchestrator
"""
def handleSetRates(idx):
    print("Setting commission rates for {0}".format(State.orchestrators[idx].source_address))

    # Get reward percentage to keep
    while True:
        try:
            reward_input = input("Enter % of rewards to keep (e.g., 30 or 11.5 for 30% or 11.5%): ").strip()
            # Handle different number formats
            reward_percent = parsePercentage(reward_input)
            if 0 <= reward_percent <= 100:
                break
            else:
                print("Please enter a percentage between 0 and 100")
        except ValueError:
            print("Please enter a valid number (e.g., 30 or 11.5)")

    # Get fee percentage to keep
    while True:
        try:
            fee_input = input("Enter % of fees to keep (e.g., 30 or 11.5 for 30% or 11.5%): ").strip()
            # Handle different number formats
            fee_percent = parsePercentage(fee_input)
            if 0 <= fee_percent <= 100:
                break
            else:
                print("Please enter a percentage between 0 and 100")
        except ValueError:
            print("Please enter a valid number (e.g., 30 or 11.5)")

    # Confirm the transaction
    print("\n{0} will keep {1}% of rewards and {2}% of fees".format(
        State.orchestrators[idx].source_address, reward_percent, fee_percent))
    print("This means delegators will receive {0}% of rewards and {1}% of fees".format(
        100 - reward_percent, 100 - fee_percent))
    print("Enter 1 to confirm. Enter anything else to abort.")

    confirmChoice = getInputAsInt()
    if confirmChoice == 1:
        Contract.doTranscoder(idx, reward_percent, fee_percent)
    else:
        print("Transaction aborted")


### Treasury proposals


"""
@brief Handler for voting on a proposal
"""
def handleVote(idx, proposalId):
    while True:
        print("{0} wants to vote".format(State.orchestrators[idx].source_address))
        options = ["3. Abstain", "2. Vote for the proposal", "1. Vote against the proposal", "0. Back to wallet selection"]
        printOptions(options)
        voteChoice = getInputAsInt()
        if voteChoice == 0:
            return
        elif voteChoice == -1:
            continue
        else:
            if voteChoice < 4:
                voteVal = -1 #< 0 = Against, 1 = For, 2 = Abstain
                reason = input("Type in a reason or leave empty to vote without reason: ")
                # Finally ask them to confirm
                reasonString = State.orchestrators[idx].source_address + " is about to "
                if voteChoice == 3:
                    reasonString += "vote ABSTAIN this proposal "
                    voteVal = 2
                if voteChoice == 2:
                    reasonString += "vote FOR this proposal"
                    voteVal = 1
                if voteChoice == 1:
                    reasonString += "vote AGAINST this proposal"
                    voteVal = 0
                if reason == "":
                    reasonString += " without a reason"
                else:
                    reasonString += " with reason: '" + reason + "'"
                print(reasonString)
                print("Enter 1 to confirm. Enter anything else to abort.")
                confirmChoice = getInputAsInt()
                if (confirmChoice != 1):
                    continue
                # And cast the vote
                if reason == "":
                    Contract.doCastVote(idx, proposalId, voteVal)
                else:
                    Contract.doCastVoteWithReason(idx, proposalId, voteVal, reason)
                return
            else:
                print("UNIMPL: chose {0}".format(voteChoice))

"""
@brief Handler for choosing a wallet to vote with
"""
def handleProposal(proposals, proposalIdx):
    proposal = proposals[proposalIdx]
    while True:
        # Refresh votes
        currentVotes = Contract.getVotes(proposal["proposalId"])
        sumVotes = currentVotes[0] + currentVotes[1] + currentVotes[2]
        amountAgainst = currentVotes[0]
        amountFor = currentVotes[1]
        amountAbstained = currentVotes[2]
        print("Currently {0:.0f} LPT ({1:.0f}%) is in favour, {2:.0f} LPT ({3:.0f}%) is in against, {4:.0f} LPT ({5:.0f}%) has abstained".format(
            amountFor, amountFor/sumVotes * 100, amountAgainst, amountAgainst/sumVotes * 100, amountAbstained, amountAbstained/sumVotes * 100
        ))
        # First build a list of eligible orchs
        canVoteIdx = []
        options = []
        for orchIdx in range(len(State.orchestrators)):
            hasVoted = Contract.hasVoted(proposal["proposalId"], State.orchestrators[orchIdx].source_checksum_address)
            if hasVoted:
                options.append("{0}. {1} has already voted on this proposal".format(orchIdx + 1, State.orchestrators[orchIdx].source_address))
            else:
                canVoteIdx.append(orchIdx)
                options.append("{0}. Vote with {1}".format(orchIdx + 1, State.orchestrators[orchIdx].source_address))
        options.append("0. Back to proposals")
        # Ask which wallet to vote with
        printOptions(options)
        choice = getInputAsInt()
        if choice == 0:
            return
        elif choice == -1:
            continue
        else:
            orchIdx = choice - 1
            if orchIdx < len(State.orchestrators):
                if orchIdx in canVoteIdx:
                    handleVote(orchIdx, proposal["proposalId"])
                else:
                    print("{0} has already voted on this proposal".format(State.orchestrators[orchIdx].source_address))
            else:
                print("UNIMPL: chose {0}".format(choice))

"""
@brief Handler for choosing a treasury proposal
"""
def handleTreasury():
    proposals = Contract.getProposals()

    if not proposals:
        print("\nNo active proposals found.")
        return

    while True:
        options = []
        for idx, proposal in enumerate(proposals):
            options.append("{0}. {1}".format(idx + 1, proposal["title"]))
        options.append("0. Back to menu")
        printOptions(options)
        choice = getInputAsInt()

        if choice == 0:
            break
        elif choice == -1:
            continue
        else:
            proposalIdx = choice - 1
            if proposalIdx < len(proposals):
                handleProposal(proposals, proposalIdx)
            else:
                print("UNIMPL: chose {0}".format(choice))


### LIP Governance Polls


"""
@brief Handler for voting on a LIP poll
"""
def handlePollVote(idx, pollAddress):
    while True:
        print("{0} wants to vote on poll".format(State.orchestrators[idx].source_address))
        options = ["1. Vote YES", "2. Vote NO", "0. Back to wallet selection"]
        printOptions(options)
        voteChoice = getInputAsInt()
        if voteChoice == 0:
            return
        elif voteChoice == -1:
            continue
        elif voteChoice in [1, 2]:
            choiceId = 0 if voteChoice == 1 else 1  # 0=Yes, 1=No
            choiceName = "YES" if choiceId == 0 else "NO"
            print("{0} is about to vote {1} on this poll".format(
                State.orchestrators[idx].source_address, choiceName))
            print("Enter 1 to confirm. Enter anything else to abort.")
            confirmChoice = getInputAsInt()
            if confirmChoice == 1:
                Contract.doCastPollVote(idx, pollAddress, choiceId)
            return
        else:
            print("UNIMPL: chose {0}".format(voteChoice))

"""
@brief Handler for choosing a wallet to vote on a poll
"""
def handlePoll(polls, pollIdx):
    poll = polls[pollIdx]
    while True:
        options = []
        for orchIdx in range(len(State.orchestrators)):
            hasVoted, choiceId = Contract.getVoteStatus(poll["pollAddress"], State.orchestrators[orchIdx].source_checksum_address)
            if hasVoted:
                voteName = "YES" if choiceId == 0 else "NO"
                options.append("{0}. {1} - Voted {2}".format(orchIdx + 1, State.orchestrators[orchIdx].source_address, voteName))
            else:
                options.append("{0}. {1} - Can vote".format(orchIdx + 1, State.orchestrators[orchIdx].source_address))
        options.append("0. Back to polls")
        printOptions(options)
        choice = getInputAsInt()
        if choice == 0:
            return
        elif choice == -1:
            continue
        else:
            orchIdx = choice - 1
            if orchIdx < len(State.orchestrators):
                hasVoted, _ = Contract.getVoteStatus(poll["pollAddress"], State.orchestrators[orchIdx].source_checksum_address)
                if hasVoted:
                    print("{0} has already voted on this poll".format(State.orchestrators[orchIdx].source_address))
                else:
                    handlePollVote(orchIdx, poll["pollAddress"])
            else:
                print("UNIMPL: chose {0}".format(choice))

"""
@brief Handler for choosing a LIP governance poll
"""
def handleGovernance():
    polls = Contract.getPolls()

    if not polls:
        print("\nNo LIP polls found.")
        return

    while True:
        options = []
        for idx, poll in enumerate(polls):
            addr = poll["pollAddress"]
            shortAddr = addr[:6] + "..." + addr[-4:]
            options.append("{0}. Poll {1}".format(idx + 1, shortAddr))
        options.append("0. Back to menu")
        printOptions(options)
        choice = getInputAsInt()

        if choice == 0:
            break
        elif choice == -1:
            continue
        else:
            pollIdx = choice - 1
            if pollIdx < len(polls):
                handlePoll(polls, pollIdx)
            else:
                print("UNIMPL: chose {0}".format(choice))
