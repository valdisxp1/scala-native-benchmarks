#!/usr/bin/env python2
import os
import errno
import subprocess as subp
import shutil as sh
import argparse
import multiprocessing as mp


def mkdir(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def slurp(path):
    with open(path) as f:
        return f.read().strip()


def where(cmd):
    if os.path.isfile(cmd):
        return cmd
    else:
        paths = os.environ['PATH'].split(os.pathsep)
        for p in paths:
            f = os.path.join(p, cmd)
            if os.path.isfile(f):
                return f
        else:
            return None


def run(cmd, env=None, wd=None):
    print(">>> " + str(cmd))
    if wd == None:
        return subp.check_output(cmd, stderr=subp.STDOUT, env=env)
    else:
        return subp.check_output(cmd, stderr=subp.STDOUT, env=env, cwd=wd)


scala_native_dir = "../scala-native"


def fetch():
    git_fetch = ['git', 'fetch', '--all']
    try:
        run(git_fetch, wd=scala_native_dir)
    except:
        pass


def get_ref(ref):
    git_rev_parse = ['git', 'rev-parse', '--short', ref]
    try:
        return run(git_rev_parse, wd=scala_native_dir).strip()
    except subp.CalledProcessError as err:
        out = err.output
        print "Cannot find", ref, "!"
        print out
        return None


def compile_scala_native(ref, sha1):
    if ref != "HEAD":
        git_checkout = ['git', 'checkout', sha1]
        try:
            print run(git_checkout, wd=scala_native_dir)
        except subp.CalledProcessError as err:
            out = err.output
            print "Cannot checkout", sha1, "!"
            print out
            return False

    compile_cmd = [sbt, '-no-colors', '-J-Xmx2G', 'rebuild', 'sandbox/run']
    compile_env = os.environ.copy()
    compile_env["SCALANATIVE_GC"] = "immix"
    local_scala_repo_dir = os.path.abspath("../scala-2.11.11-only")
    if os.path.isdir(local_scala_repo_dir):
        compile_env["SCALANATIVE_SCALAREPO"] = local_scala_repo_dir

    try:
        run(compile_cmd, compile_env, wd=scala_native_dir)
        return True
    except subp.CalledProcessError as err:
        out = err.output
        print "Compilation failure!"
        print out
        return False


def compile(bench, compilecmd):
    cmd = [sbt, '-no-colors', '-J-Xmx2G', 'clean']
    cmd.append('set mainClass in Compile := Some("{}")'.format(bench))
    cmd.append(compilecmd)
    return run(cmd)


sbt = where('sbt')

all_benchmarks = [
    'bounce.BounceBenchmark',
    'list.ListBenchmark',
    'richards.RichardsBenchmark',
    'queens.QueensBenchmark',
    'permute.PermuteBenchmark',
    'deltablue.DeltaBlueBenchmark',
    'tracer.TracerBenchmark',
    'brainfuck.BrainfuckBenchmark',
    'json.JsonBenchmark',
    'cd.CDBenchmark',
    'kmeans.KmeansBenchmark',
    'gcbench.GCBenchBenchmark',
    'mandelbrot.MandelbrotBenchmark',
    'nbody.NbodyBenchmark',
    'sudoku.SudokuBenchmark',
]

stable = 'scala-native-0.3.8'
latest = 'scala-native-0.3.9-SNAPSHOT'
baseline = [
    'jvm',
    stable,
]
default = baseline + [latest]

confs_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + "/confs"

configurations = all_configs = next(os.walk(confs_path))[1]

graalvm = [
    'native-image',
    'native-image-pgo',
]

if 'GRAALVM_HOME' in os.environ:
    baseline += graalvm
else:
    for g in graalvm:
        all_configs.remove(g)

default_runs = 20
default_batches = 3000
default_par = 1
batch_size = 1


def expand_wild_cards(arg):
    if arg.startswith("latest"):
        return latest + arg[len("latest"):]
    elif arg.startswith("stable"):
        return stable + arg[len("stable"):]
    else:
        return arg


def ref_parse(arg):
    parts = arg.split("@")
    if len(parts) == 3:
        return parts[0], (parts[2] + "/" + parts[1])
    elif len(parts) == 2:
        return parts[0], parts[1]
    else:
        return arg, None


def size_parse(arg):
    parts = arg.split(":")
    if len(parts) == 1:
        return [arg, arg]
    else:
        return parts


def generate_choices(direct_choices):
    results = direct_choices
    for dir in direct_choices:
        if dir.startswith(latest):
            results += ["latest" + dir[len(latest):]]
        if dir.startswith(stable):
            results += ["stable" + dir[len(stable):]]
    return results


def single_run(to_run):
    n = to_run["n"]
    runs = to_run["runs"]
    cmd = to_run["cmd"]
    resultsdir = to_run["resultsdir"]
    conf = to_run["conf"]
    bench = to_run["bench"]
    gcstats = to_run["gcstats"]
    minsize = to_run["size"][0]
    maxsize = to_run["size"][1]

    print('--- run {}/{}'.format(n, runs))
    my_env = os.environ.copy()
    if gcstats:
        my_env["SCALANATIVE_STATS_FILE"] = os.path.join(resultsdir, str(n) + ".gc.csv")

    if minsize != "default":
        my_env["SCALANATIVE_MIN_HEAP_SIZE"] = minsize
    elif "SCALANATIVE_MIN_HEAP_SIZE" in my_env:
        del my_env["SCALANATIVE_MIN_HEAP_SIZE"]

    if maxsize != "default":
        my_env["SCALANATIVE_MAX_HEAP_SIZE"] = maxsize
    elif "SCALANATIVE_MAX_HEAP_SIZE" in my_env:
        del my_env["SCALANATIVE_MAX_HEAP_SIZE"]

    try:
        out = run(cmd, my_env)
        with open(os.path.join(resultsdir, str(n)), 'w+') as resultfile:
            resultfile.write(out)
        return []
    except subp.CalledProcessError as err:
        out = err.output
        print "Failure!"
        print out
        with open(os.path.join(resultsdir, str(n) + ".failed"), 'w+') as failfile:
            failfile.write(out)
        return [dict(conf=conf, bench=bench, run=n)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", help="suffix added to results")
    parser.add_argument("--runs", help="number of runs", type=int, default=default_runs)
    parser.add_argument("--batches", help="number of batches per run", type=int, default=default_batches)
    parser.add_argument("--benchmark", help="benchmarks to run", action='append')
    parser.add_argument("--size", help="different size settings to use", action='append')
    parser.add_argument("--par", help="number of parallel processes", type=int, default=default_par)
    parser.add_argument("--gc", help="gather gc statistics", action="store_true")
    parser.add_argument("--overwrite", help="overwrite old results", action="store_true")
    parser.add_argument("--append", help="do not delete old data", action="store_true")
    parser.add_argument("set", nargs='*', default="default")
    args = parser.parse_args()
    print args

    runs = args.runs
    batches = args.batches
    par = args.par

    if args.benchmark != None:
        benchmarks = []
        for b in args.benchmark:
            benchmarks += filter(lambda s: s.startswith(b), all_benchmarks)
    else:
        benchmarks = all_benchmarks

    if args.size != None:
        sizes = []
        for size_str in args.size:
            sizes += [size_parse(size_str)]
    else:
        sizes = [["default", "default"]]

    configurations = []
    for choice in args.set:
        expanded = expand_wild_cards(choice)
        if expanded == "baseline":
            configurations += baseline
        elif expanded == "default":
            configurations = default
        else:
            configurations += [expanded]

    print "configurations:", configurations
    print "benchmarks:", benchmarks
    print "heap sizes:", sizes

    should_fetch = False
    for conf in configurations:
        if '@' in conf:
            should_fetch = True
            break

    if should_fetch:
        fetch()

    suffix = ""
    if runs != default_runs:
        suffix += "-r" + str(runs)
    if batches != default_batches:
        suffix += "-b" + str(batches)
    if par != default_par:
        suffix += "-p" + str(par)
    if args.gc:
        suffix += "-gc"
    if args.suffix is not None:
        suffix += "_" + args.suffix

    failed = []
    result_dirs = []
    pool = None
    if par > 1:
        pool = mp.Pool(par)

    for conf in configurations:
        conf_name, ref = ref_parse(conf)

        if ref == None:
            sha1 = None
            root_dir = os.path.join('results', conf_name + suffix)
        else:
            sha1 = get_ref(ref)
            if sha1 == None:
                continue
            root_dir = os.path.join('results', conf + "." + sha1 + "." + suffix)

        if sha1 != None:
            success = compile_scala_native(ref, sha1)
            if not success:
                continue

        for size in sizes:

            if size == ["default", "default"]:
                sized_dir = root_dir
            else:
                size_str = "size_" + size[0] + "-" + size[1]
                sized_dir = os.path.join(root_dir, size_str)

            if not args.overwrite and os.path.isfile(os.path.join(sized_dir, ".complete")):
                print  sized_dir, "already complete, skipping"
                continue

            if not args.append:
                sh.rmtree(sized_dir, ignore_errors=True)

            mkdir(sized_dir)

            for bench in benchmarks:
                print('--- conf: {}, bench: {}'.format(conf, bench))

                input = slurp(os.path.join('input', bench))
                output = slurp(os.path.join('output', bench))
                compilecmd = slurp(os.path.join('confs', conf_name, 'compile'))
                runcmd = slurp(os.path.join('confs', conf_name, 'run')) \
                    .replace('$BENCH', bench) \
                    .replace('$HOME', os.environ['HOME']).split(' ')

                if os.path.exists(os.path.join('confs', conf_name, 'build.sbt')):
                    sh.copyfile(os.path.join('confs', conf_name, 'build.sbt'), 'build.sbt')
                else:
                    os.remove('build.sbt')

                if os.path.exists(os.path.join('confs', conf_name, 'plugins.sbt')):
                    sh.copyfile(os.path.join('confs', conf_name, 'plugins.sbt'), 'project/plugins.sbt')
                else:
                    os.remove('project/plugins.sbt')

                compile(bench, compilecmd)

                resultsdir = os.path.join(sized_dir, bench)
                mkdir(resultsdir)

                cmd = []
                cmd.extend(runcmd)
                cmd.extend([str(batches), str(batch_size), input, output])

                to_run = []
                for n in xrange(runs):
                    to_run += [
                        dict(runs=runs, cmd=cmd, resultsdir=resultsdir, conf=conf, bench=bench, n=n, gcstats=args.gc,
                             size=size)]

                if par == 1:
                    for tr in to_run:
                        failed += single_run(tr)
                else:
                    failed += sum(pool.map(single_run, to_run), [])

            # mark it as complete
            open(os.path.join(sized_dir, ".complete"), 'w+').close()
            result_dirs += [sized_dir]

    print "results:"
    for dir in result_dirs:
        print dir

    if len(failed) > 0:
        print("{} benchmarks failed ".format(len(failed)))
        for fail in failed:
            print fail
        exit(1)
