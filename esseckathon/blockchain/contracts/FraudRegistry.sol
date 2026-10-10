// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FraudRegistry - registre partage d'alertes de fraude entre banques
/// @notice Aucune donnee personnelle en clair : les comptes sont pseudonymises par
///         keccak256(sel du consortium + account_id), calcule hors chaine. C'est une
///         pseudonymisation (le RGPD s'applique toujours) ; en production, viser une
///         intersection privee d'ensembles (PSI) entre banques.
contract FraudRegistry {
    // ------------------------------------------------------------------ types

    /// Motifs detectes par le module 2 (meme ordre que PATTERN_TYPES dans shared/schema.py)
    enum Pattern {
        FanInRedistribution,
        Smurfing,
        LayeringChain,
        DormantReactivation,
        Cycle,
        FanInOnly
    }

    struct Report {
        bool active;
        uint8 score;
        Pattern pattern;
        bytes32 evidenceHash;  // hash du dossier de preuve (stocke hors chaine)
        uint64 reportedAt;
    }

    // ----------------------------------------------------------------- etat

    address public admin;
    mapping(address => bool) public isMember;
    mapping(address => string) public memberName;

    mapping(bytes32 => mapping(address => Report)) private _reports;
    /// Banques ayant deja signale ce compte (au plus une entree par banque)
    mapping(bytes32 => address[]) private _reporters;

    // ---------------------------------------------------------------- events

    event MemberAdded(address indexed member, string name);
    event MemberRemoved(address indexed member);
    event DatasetAnchored(bytes32 indexed datasetHash, string label, address indexed by, uint64 at);
    event AlertReported(
        bytes32 indexed accountHash,
        address indexed reporter,
        uint8 score,
        Pattern pattern,
        bytes32 evidenceHash,
        uint64 at
    );
    event AlertRetracted(bytes32 indexed accountHash, address indexed reporter, uint64 at);

    // ---------------------------------------------------------------- erreurs

    error NotAdmin();
    error NotMember();
    error InvalidScore();
    error NoActiveReport();

    modifier onlyAdmin() {
        if (msg.sender != admin) revert NotAdmin();
        _;
    }

    modifier onlyMember() {
        if (!isMember[msg.sender]) revert NotMember();
        _;
    }

    constructor(string memory adminBankName) {
        admin = msg.sender;
        isMember[msg.sender] = true;
        memberName[msg.sender] = adminBankName;
        emit MemberAdded(msg.sender, adminBankName);
    }

    // ------------------------------------------------------------ consortium

    function addMember(address member, string calldata name) external onlyAdmin {
        isMember[member] = true;
        memberName[member] = name;
        emit MemberAdded(member, name);
    }

    /// @notice Les signalements d'un membre retire cessent immediatement de compter dans isFlagged
    function removeMember(address member) external onlyAdmin {
        isMember[member] = false;
        emit MemberRemoved(member);
    }

    // ------------------------------------------------------------ donnees

    /// @notice Notarise un jeu de donnees (ex. SHA-256 du manifest + CSV)
    function anchorDataset(bytes32 datasetHash, string calldata label) external onlyMember {
        emit DatasetAnchored(datasetHash, label, msg.sender, uint64(block.timestamp));
    }

    // ------------------------------------------------------------ alertes

    /// @notice Signale (ou met a jour) un compte suspect pour la banque appelante
    function reportAlert(bytes32 accountHash, uint8 score, Pattern pattern, bytes32 evidenceHash)
        external
        onlyMember
    {
        if (score > 100) revert InvalidScore();

        Report storage r = _reports[accountHash][msg.sender];
        if (r.reportedAt == 0) {
            _reporters[accountHash].push(msg.sender);
        }
        r.active = true;
        r.score = score;
        r.pattern = pattern;
        r.evidenceHash = evidenceHash;
        r.reportedAt = uint64(block.timestamp);

        emit AlertReported(accountHash, msg.sender, score, pattern, evidenceHash, uint64(block.timestamp));
    }

    /// @notice Retire son propre signalement (faux positif confirme, ex. cagnotte de mariage)
    function retractAlert(bytes32 accountHash) external onlyMember {
        Report storage r = _reports[accountHash][msg.sender];
        if (!r.active) revert NoActiveReport();
        r.active = false;
        emit AlertRetracted(accountHash, msg.sender, uint64(block.timestamp));
    }

    // ------------------------------------------------------------ lecture

    /// @notice Verification avant virement : ce beneficiaire est-il signale ?
    /// @dev Recalcule a chaque appel sur les seuls signalements actifs de membres actuels :
    ///      un retrait ou l'exclusion d'une banque fait donc redescendre le score.
    function isFlagged(bytes32 accountHash)
        external
        view
        returns (bool flagged, uint32 reportCount, uint8 maxScore, uint64 lastReportAt)
    {
        address[] storage reporters = _reporters[accountHash];
        for (uint256 i = 0; i < reporters.length; i++) {
            Report storage r = _reports[accountHash][reporters[i]];
            if (!r.active || !isMember[reporters[i]]) continue;
            reportCount += 1;
            if (r.score > maxScore) maxScore = r.score;
            if (r.reportedAt > lastReportAt) lastReportAt = r.reportedAt;
        }
        flagged = reportCount > 0;
    }

    function getReport(bytes32 accountHash, address reporter) external view returns (Report memory) {
        return _reports[accountHash][reporter];
    }

    function getReporters(bytes32 accountHash) external view returns (address[] memory) {
        return _reporters[accountHash];
    }
}
