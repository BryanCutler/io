sh_binary(
    name = "build_pip_pkg",
    srcs = ["build_pip_pkg.sh"],
    data = [
        "LICENSE",
        "MANIFEST.in",
        "setup.py",
	"tensorflow_io/__init__.py",
        "//tensorflow_io/hadoop:hadoop_py",
        "//tensorflow_io/ignite:ignite_py",
        "//tensorflow_io/kafka:kafka_py",
        "//tensorflow_io/kinesis:kinesis_py",
    ],
)
