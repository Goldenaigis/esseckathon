// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title GasFunder - distribue le jeton natif de la L1 (gas) a de nombreux wallets en une transaction
contract GasFunder {
    error LengthMismatch();
    error WrongValue();
    error TransferFailed(address to);

    function fund(address[] calldata to, uint256[] calldata amounts) external payable {
        if (to.length != amounts.length) revert LengthMismatch();
        uint256 total;
        for (uint256 i = 0; i < to.length; i++) {
            total += amounts[i];
            (bool ok, ) = payable(to[i]).call{value: amounts[i]}("");
            if (!ok) revert TransferFailed(to[i]);
        }
        if (total != msg.value) revert WrongValue();
    }
}
