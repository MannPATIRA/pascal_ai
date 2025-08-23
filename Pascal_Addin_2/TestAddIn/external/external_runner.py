import sys 

if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else ""
    processed = f"Processed: {text.strip().upper()}"
    print(processed)