# All logic related to direct interaction with the user
# Like asking the user for a password or voting on a proposal
# Import our own libraries
from lib import State

"""
@brief Print all user choices
"""
def printOptions():
    options = [
        "1. TBA",
        "0. Start siphoning. Press `CTRL + z`or `CTRL + \\` if you want to switch back to interactive mode"
    ]
    print("\nPlease choose an option:")
    for option in options:
        print(option)
    print()
    
"""
@brief Handler for user choices
"""
def parseOption(choice):
    print("UNIMPL: chose {0}".format(choice))
    pass

"""
@brief Asks the user to give us a number
@return -1 on failure, else an integer
"""
def getInputAsInt():
    choice = input("Enter a number (choose 0 to proceed): ")
    
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
        printOptions()
        choice = getInputAsInt()

        if choice == 0:
            print("Siphoning... 💸")
            State.require_user_input = False
            break
        else:
            parseOption(choice)
    
