# VaultStock Supplementary Documentation & Extras 📚

This directory holds auxiliary engineering documentation, DBMS course deliverables, viva preparation guides, and the automated verification suite.

## 📑 Contents

1. **[PRESENTATION_GUIDE.md](file:///d:/DBMS%20Project/vaultstock/extras/PRESENTATION_GUIDE.md)**
   - 2-minute live demo script (Demonstrating immutable ledger & live tampering detection).
   - Top 10 viva exam questions and clear technical answers.

2. **[DATA_DICTIONARY.md](file:///d:/DBMS%20Project/vaultstock/extras/DATA_DICTIONARY.md)**
   - Column-by-column specification of all relational tables (`users`, `products`, `movements`, `audit_log`).
   - Primary keys, foreign key references, and CHECK constraints.

3. **[ER_DIAGRAM.md](file:///d:/DBMS%20Project/vaultstock/extras/ER_DIAGRAM.md)**
   - Mermaid Entity-Relationship diagram showing table cardinalities and relationships.
   - Design trade-off rationale (derived stock balance vs stored mutable quantity).

4. **[NORMALIZATION.md](file:///d:/DBMS%20Project/vaultstock/extras/NORMALIZATION.md)**
   - Step-by-step formal normalization proofs from 0NF to 1NF, 2NF, and 3NF/BCNF.
   - Functional dependency mappings.

5. **[TEST_CASES.md](file:///d:/DBMS%20Project/vaultstock/extras/TEST_CASES.md)**
   - Security and functional test matrix mapping threats to test routines.

6. **[THREAT_MODEL.md](file:///d:/DBMS%20Project/vaultstock/extras/THREAT_MODEL.md)**
   - STRIDE threat model analysis for inventory databases.
   - Attack vectors evaluated (replay attacks, tail truncation, SQL injection, insider tampering).

7. **[test_suite.py](file:///d:/DBMS%20Project/vaultstock/extras/test_suite.py)**
   - End-to-end automated verification script covering 22 security checks (T1–T22) and 4 core functional workflows (F1–F4).

