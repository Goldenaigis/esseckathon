// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title EURToken - euro de simulation FraudNet (EURF), 2 decimales comme les montants du jeu de donnees
/// @notice Chaque virement FraudNet devient un appel a pay(), qui emet un evenement Payment
///         portant la reference du virement d'origine (tx_id) et son horodatage simule.
contract EURToken is ERC20, Ownable {
    event Payment(
        address indexed from,
        address indexed to,
        uint256 amount,
        bytes32 indexed txRef,
        uint64 originalTs
    );

    error LengthMismatch();

    constructor() ERC20("Euro FraudNet", "EURF") Ownable(msg.sender) {}

    function decimals() public pure override returns (uint8) {
        return 2;
    }

    /// @notice Soldes initiaux des comptes (role de banque centrale du consortium)
    function batchMint(address[] calldata to, uint256[] calldata amounts) external onlyOwner {
        if (to.length != amounts.length) revert LengthMismatch();
        for (uint256 i = 0; i < to.length; i++) {
            _mint(to[i], amounts[i]);
        }
    }

    /// @notice Virement avec reference : txRef = tx_id FraudNet, originalTs = horodatage simule
    function pay(address to, uint256 amount, bytes32 txRef, uint64 originalTs) external {
        _transfer(msg.sender, to, amount);
        emit Payment(msg.sender, to, amount, txRef, originalTs);
    }
}
