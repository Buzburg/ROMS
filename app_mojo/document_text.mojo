"""Bounded Unicode cleanup and passage splitting for local ingestion."""


def clean_text(text: String) raises -> String:
    if text.byte_length() > 32 * 1024 * 1024:
        raise Error("Decoded document exceeds the text limit")
    var result = String()
    var carriage = False
    for part in text.codepoint_slices():
        var iterator = part.codepoints()
        var cp = Int(iterator.__next__())
        if cp == 10 and carriage:
            carriage = False
            continue
        carriage = cp == 13
        if cp == 13 or cp == 8232 or cp == 8233:
            result += "\n"
        elif cp == 65279:
            continue
        elif cp == 160 or (cp < 32 and cp != 9 and cp != 10) or cp == 127:
            result += " "
        else:
            result += String(part)
    return result


def split_passages(text: String) raises -> List[String]:
    if text.byte_length() > 32 * 1024 * 1024:
        raise Error("Decoded passage exceeds the text limit")
    var result = List[String]()
    var block = String()
    var count = 0
    var previous_newline = False
    for part in text.codepoint_slices():
        var newline = part == "\n"
        var whitespace = newline or part == " " or part == "\t"
        block += String(part)
        count += 1
        if (newline and previous_newline) or (count >= 512 and whitespace) or count >= 768:
            if block.strip().byte_length() > 0:
                result.append(String(block.strip()))
                if len(result) > 20000:
                    raise Error("Document contains too many passages")
            block = String()
            count = 0
        previous_newline = newline
    if block.strip().byte_length() > 0:
        result.append(String(block.strip()))
        if len(result) > 20000:
            raise Error("Document contains too many passages")
    return result^
