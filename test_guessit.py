import guessit
import sys

def test():
    try:
        result = guessit.guessit("The.Mentalist.S04E20.720p.WEB-DL.x264.350MB-PAHE.in.mkv")
        print("Success:", result)
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
