"""CPython boundary: convert once, then execute native Mojo retrieval kernels."""
from std.os import abort
from std.python import Python, PythonObject
from std.python.bindings import PythonModuleBuilder
from app_mojo.search_kernels import expand_terms, fuse_ranks
from app_mojo.document_text import clean_text, split_passages


def expand(query: PythonObject, terms: PythonObject) raises -> PythonObject:
    if len(terms) > 2048:
        raise Error("Too many vocabulary terms")
    var native_terms = List[String](capacity=len(terms))
    for term in terms:
        native_terms.append(String(py=term))
    var indices = expand_terms(String(py=query), native_terms)
    var output = Python.list()
    for index in indices:
        output.append(index)
    return output


def fuse(lexical: PythonObject, vectors: PythonObject, limit: PythonObject) raises -> PythonObject:
    if len(lexical) > 300 or len(vectors) > 300:
        raise Error("Too many rank candidates")
    var native_lexical = List[Int](capacity=len(lexical))
    var native_vectors = List[Int](capacity=len(vectors))
    for key in lexical:
        native_lexical.append(Int(py=key))
    for key in vectors:
        native_vectors.append(Int(py=key))
    var hits = fuse_ranks(native_lexical, native_vectors, Int(py=limit))
    var output = Python.list()
    for hit in hits:
        output.append(Python.tuple(hit.key, hit.score, hit.lexical_rank, hit.vector_rank))
    return output


def clean(text: PythonObject) raises -> PythonObject:
    return PythonObject(clean_text(String(py=text)))


def passages(text: PythonObject) raises -> PythonObject:
    var parts = split_passages(String(py=text))
    var output = Python.list()
    for part in parts:
        output.append(part)
    return output


@export
def PyInit_roms_search_native() abi("C") -> PythonObject:
    try:
        var module = PythonModuleBuilder("roms_search_native")
        module.def_function[expand]("expand")
        module.def_function[fuse]("fuse")
        module.def_function[clean]("clean")
        module.def_function[passages]("passages")
        return module.finalize()
    except error:
        abort(String("Cannot create ROMS search module: ", error))
