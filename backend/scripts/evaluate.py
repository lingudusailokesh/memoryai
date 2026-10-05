"""Small, repeatable evaluation data set for provider comparisons.

This intentionally reports no invented scores: connect the selected provider, run the
questions, then record measured accuracy/latency in README before making a claim.
"""
CASES = [
    {"conversation": "I am learning DSA in Python.", "question": "What programming language am I learning?", "expected": "Python"},
    {"conversation": "My goal is to prepare for SDE interviews.", "question": "What should I study today?", "expected": "SDE interview preparation"},
]

if __name__ == "__main__":
    for case in CASES:
        print(f"Q: {case['question']}\nExpected concept: {case['expected']}\n")
