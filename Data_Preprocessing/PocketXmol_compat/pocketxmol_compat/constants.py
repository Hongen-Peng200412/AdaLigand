"""Phase 1 适配契约中经审核的稳定枚举。"""

from __future__ import annotations

POCKETXMOL_COMMIT = "65488cf635c856101dbe703ac97e2f10f58e005c"

# 顺序必须与 PocketXMol `utils/transforms.py::FeaturizeMol` 一致。
LIGAND_ATOMIC_NUMBERS = (6, 7, 8, 9, 15, 16, 17, 5, 35, 53, 34)

# A–G Bond.type 的五维 one-hot 顺序为 single/double/triple/dative/aromatic。
AG_BOND_TO_POCKETXMOL = {0: 1, 1: 2, 2: 3, 4: 4}

# 顺序必须与 PocketXMol `utils/parser.py::PDBProtein.AA_NAME_NUMBER` 一致。
AMINO_ACIDS = (
    "ALA", "CYS", "ASP", "GLU", "PHE", "GLY", "HIS", "ILE", "LYS", "LEU",
    "MET", "ASN", "PRO", "GLN", "ARG", "SER", "THR", "VAL", "TRP", "TYR",
)
AA_TO_INDEX = {name: index for index, name in enumerate(AMINO_ACIDS)}
AA_TO_ONE_LETTER = {
    "ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F",
    "GLY": "G", "HIS": "H", "ILE": "I", "LYS": "K", "LEU": "L",
    "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R",
    "SER": "S", "THR": "T", "VAL": "V", "TRP": "W", "TYR": "Y",
}
POCKET_ATOMIC_NUMBERS = (6, 7, 8, 16)
BACKBONE_ATOM_NAMES = frozenset({"CA", "C", "N", "O"})
NUCLEIC_COMPONENTS = frozenset({"A", "C", "G", "U", "I", "DA", "DC", "DG", "DT", "DI"})

STRICT_RECEPTOR_REASONS = {
    "nucleic": "nucleic_acid_in_official_training_pocket",
    "modified": "modified_residue_in_official_training_pocket",
    "nonstandard": "nonstandard_residue_in_official_training_pocket",
}
