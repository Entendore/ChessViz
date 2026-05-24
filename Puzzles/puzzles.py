"""Built-in puzzle data for the Chess Learning App."""

PUZZLES = [
    {
        "name": "Scholar's Mate",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
        "moves": [((3, 7), (1, 5))],  # Qh5xf7#
        "desc": (
            "White checkmates in one move using the Queen.\n\n"
            "The f7 pawn is only defended by the King. Qxf7# is checkmate!"
        ),
    },
    {
        "name": "Back Rank Mate",
        "fen": "6k1/5ppp/8/8/8/8/8/R3K3 w Q - 0 1",
        "moves": [((7, 0), (0, 0))],  # Ra1-a8#
        "desc": (
            "White's Rook delivers a back rank mate.\n\n"
            "The Black King is trapped behind its own pawns. Ra8# is checkmate!"
        ),
    },
    {
        "name": "Ladder Mate",
        "fen": "8/8/8/8/8/1k6/8/R3K3 w Q - 0 1",
        "moves": [((7, 0), (0, 0))],  # Ra1-a8
        "desc": (
            "The Rook forces the King to the edge.\n\n"
            "Ra1-a8 creates a barrier the King cannot cross."
        ),
    },
    {
        "name": "Two Move Mate",
        "fen": "k7/8/1K6/8/8/8/8/7R w - - 0 1",
        "moves": [((7, 7), (7, 0)), ((7, 0), (0, 0))],  # Rh1-a1, Ra1-a8#
        "desc": (
            "White checkmates in two moves.\n"
            "1. Rh1-a1 forces the Black King to b8.\n"
            "2. Ra8# is checkmate."
        ),
    },
]