import os
import time
import tqdm
import argparse
import numpy as np
from scipy.special import comb
from threading import Thread
import signal
import subprocess
from pathlib import Path


def exec_shell(cmd_str, timeout=8, max_retries=3):
    def run_shell_func(sh):
        for attempt in range(max_retries):
            try:
                process = subprocess.Popen(sh, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = process.communicate(timeout=timeout)
                
                # Check if the generated Verilog file exists and is not empty
                if process.returncode != 0:
                    stderr_str = stderr.decode('utf-8')
                    if "Device or resource busy" in stderr_str and ".nfs" in stderr_str:
                        print(f"Warning: NFS-related error encountered (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(1)  # Wait for one second before retrying
                            continue
                
                return process.returncode == 0
                
            except subprocess.TimeoutExpired:
                process.kill()
                return False
            except Exception as e:
                print(f"Error executing command: {e}")
                return False
        return False

    result = run_shell_func(cmd_str)
    return 1 if result else 0


def cal_atk(dic_list, n, k):
    #syntax 
    sum_list = []
    for design in dic_list.keys():
        c = dic_list[design]['syntax_success']
        denominator = comb(n, k)
        numerator = comb(n - c, k)
        sum_list.append(
            1 - np.divide(
                numerator,
                denominator,
                out=np.array([0.0]),
                where=denominator != 0,
            )[0]
        )
    syntax_passk = sum(sum_list) / len(sum_list)
    
    #func
    sum_list = []
    for design in dic_list.keys():
        c = dic_list[design]['func_success']
        denominator = comb(n, k)
        numerator = comb(n - c, k)
        sum_list.append(
            1 - np.divide(
                numerator,
                denominator,
                out=np.array([0.0]),
                where=denominator != 0,
            )[0]
        )
    func_passk = sum(sum_list) / len(sum_list)
    print(f'syntax pass@{k}: {syntax_passk},   func pass@{k}: {func_passk}')


def main():
    parser = argparse.ArgumentParser(description='Run RTL evaluation')
    parser.add_argument('--path', type=str, required=True, help='path to the generated results')
    parser.add_argument('--test_prefix', type=str, default='test_', help='prefix of the test directory')
    args = parser.parse_args()

    # Get the directory where auto_run.py is located
    script_dir = Path(__file__).parent.absolute()
    args.path = Path(args.path).absolute()
    
    print(f"Using results path: {args.path}")
    print(f"Using designs path: {script_dir}")
    print(f"Using test prefix: {args.test_prefix}")

    design_name = [
        'accu',
        'adder_8bit',
        'adder_16bit',
        'adder_32bit',
        'adder_pipe_64bit',
        'asyn_fifo',
        'calendar',
        'counter_12', 
        'edge_detect',
        'freq_div',
        'fsm',
        'JC_counter',
        'multi_16bit',
        'multi_booth_8bit',
        'multi_pipe_4bit',
        'multi_pipe_8bit',
        'parallel2serial',
        'pe',
        'pulse_detect',
        'radix2_div',
        'RAM',
        'right_shifter',
        'serial2parallel',
        'signal_generator',
        'synchronizer',
        'alu',
        'div_16bit',
        'traffic_light',
        'width_8to16'
    ]

    active_designs = len(design_name)
    total_tests = len(os.listdir(args.path)) * active_designs
    progress_bar = tqdm.tqdm(total=total_tests)

    result_dic = {key: {} for key in design_name}
    for item in design_name:
        result_dic[item]['syntax_success'] = 0
        result_dic[item]['func_success'] = 0

    def test_one_file(testfile, result_dic):
        test_dir = os.path.join(args.path, testfile)
        print(f"Testing directory: {test_dir}")
        print(f"Test file: {testfile}")
        if not os.path.exists(test_dir):
            print(f"Warning: Directory {test_dir} does not exist")
            return result_dic

        for design in design_name:
            design_path = script_dir / design
            if os.path.exists(design_path / "makefile"):
                # Check if the generated Verilog file exists and is not empty
                verilog_file = Path(test_dir) / f"{design}.v"
                if not verilog_file.exists() or verilog_file.stat().st_size == 0:
                    print(f"Warning: Empty or missing file for {design}, marking as failed")
                    progress_bar.update(1)
                    continue

                try:
                    makefile_path = design_path / "makefile"
                    with open(makefile_path, "r") as file:
                        makefile_content = file.read()
                        modified_makefile_content = makefile_content.replace(
                            "${TEST_DESIGN}.v", str(Path(test_dir) / f"{design}.v")
                        )
                    with open(makefile_path, "w") as file:
                        file.write(modified_makefile_content)
                    # Run 'make vcs' in the design folder
                    os.chdir(design_path)
                    subprocess.run(["make", "vcs"], check=True)
                    simv_generated = False
                    if os.path.exists("simv"):
                        simv_generated = True

                    if simv_generated:
                        result_dic[design]['syntax_success'] += 1
                        # Run 'make sim' and check the result
                        to_flag = exec_shell("make sim > output.txt")
                        if to_flag == 1:
                            with open("output.txt", "r") as file:
                                output = file.read()
                                if "Pass" in output or "pass" in output:
                                    result_dic[design]['func_success'] += 1
                                else:
                                    print(f"Warning: Simulation failed for {design}, marking as failed")
                    
                    with open("makefile", "w") as file:
                        file.write(makefile_content)
                    clean_success = exec_shell("make clean")
                    if not clean_success:
                        print(f"Warning: Clean failed for {design}, but continuing with next test")
                except subprocess.CalledProcessError as e:
                    print(f"Warning: Compilation failed for {design}, marking as failed")
                except Exception as e:
                    print(f"Warning: Unexpected error for {design}: {str(e)}, marking as failed")
                finally:
                    os.chdir("..")
                    progress_bar.update(1)

        return result_dic

    try:
        file_id = 1
        n = 0
        while os.path.exists(os.path.join(args.path, f"{args.test_prefix}{file_id}")):
            print(f"Processing test directory {args.test_prefix}{file_id}")
            result_dic = test_one_file(f"{args.test_prefix}{file_id}", result_dic)
            n += 1
            file_id += 1
        print(result_dic)
        if n > 0:
            print("\nPass@1 metrics:")
            cal_atk(result_dic, n, 1)
            print("\nPass@5 metrics:")
            cal_atk(result_dic, n, 5)
        else:
            print("No test directories found!")
        total_syntax_success = 0
        total_func_success = 0
        for item in design_name:
            if result_dic[item]['syntax_success'] != 0:
                total_syntax_success += 1
            if result_dic[item]['func_success'] != 0:
                total_func_success += 1
        print(f'\ntotal_syntax_success: {total_syntax_success}/{len(design_name)}')
        print(f'total_func_success: {total_func_success}/{len(design_name)}')
    finally:
        progress_bar.close()
        # Force clean all design directories
        print("\nCleaning up all design directories...")
        for design in design_name:
            design_path = script_dir / design
            if os.path.exists(design_path / "makefile"):
                try:
                    os.chdir(design_path)
                    # Run make clean silently
                    subprocess.run(["make", "clean"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    # Additional cleanup for any remaining files
                    subprocess.run("rm -rf *.log csrc simv* *.key *.vpd DVEfiles coverage *.vdb output.txt", 
                                 shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    # Revert any changes to makefile
                    subprocess.run(["git", "checkout", "--", "."], 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e:
                    print(f"Warning: Cleanup failed for {design}: {str(e)}")
                finally:
                    os.chdir(script_dir)
        print("Cleanup completed.")


if __name__ == "__main__":
    main()

"""
python auto_run.py --path ./results --test_prefix test_
python auto_run.py --path ../results/_gpt4o --test_prefix t
"""