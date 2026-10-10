// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FraudRegistry - registre partage d'alertes de fraude entre banques
/// @notice Aucune donnee personnelle n'est stockee : les comptes sont identifies
///         par keccak256(sel du consortium + account_id), calcule hors chaine.
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

    struct AccountStatus {
        uint32 reportCount;    // nombre de banques ayant un signalement actif
        uint8 maxScore;        // score de risque maximal signale (0-100)
        uint64 lastReportAt;   // horodatage du dernier signalement
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

    mapping(bytes32 => AccountStatus) private _status;
    mapping(bytes32 => mapping(address => Report)) private _reports;

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
        AccountStatus storage s = _status[accountHash];

        if (!r.active) {
            s.reportCount += 1;
        }
        r.active = true;
        r.score = score;
        r.pattern = pattern;
        r.evidenceHash = evidenceHash;
        r.reportedAt = uint64(block.timestamp);

        if (score > s.maxScore) s.maxScore = score;
        s.lastReportAt = uint64(block.timestamp);

        emit AlertReported(accountHash, msg.sender, score, pattern, evidenceHash, uint64(block.timestamp));
    }

    /// @notice Retire son propre signalement (faux positif confirme, ex. cagnotte de mariage)
    function retractAlert(bytes32 accountHash) external onlyMember {
        Report storage r = _reports[accountHash][msg.sender];
        if (!r.active) revert NoActiveReport();
        r.active = false;
        _status[accountHash].reportCount -= 1;
        if (_status[accountHash].reportCount == 0) {
            _status[accountHash].maxScore = 0;
        }
        emit AlertRetracted(accountHash, msg.sender, uint64(block.timestamp));
    }

    // ------------------------------------------------------------ lecture

    /// @notice Verification avant virement : ce beneficiaire est-il signale ?
    function isFlagged(bytes32 accountHash)
        external
        view
        returns (bool flagged, uint32 reportCount, uint8 maxScore, uint64 lastReportAt)
    {
        AccountStatus memory s = _status[accountHash];
        return (s.reportCount > 0, s.reportCount, s.maxScore, s.lastReportAt);
    }

    function getReport(bytes32 accountHash, address reporter) external view returns (Report memory) {
        return _reports[accountHash][reporter];
    }
}
