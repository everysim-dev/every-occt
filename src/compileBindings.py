#!/usr/bin/python3

import os
import tempfile
import shutil

from joblib import delayed
from Common import TMP_DIR, ocIncludePaths, additionalIncludePaths, tryExcept
from plumbum import local

from argparse import ArgumentParser
from Common import buildOptions

from Common import console

import sys
import re

from parallelProgress import ParallelProgress

sys.path.append('/emsdk/upstream/emscripten')


LIBRARY_BASE_PATH = "/opencascade.js/build/bindings"

# 문제가 있는 파일과 그에 필요한 추가 헤더 매핑
PROBLEMATIC_FILES_HEADERS = {
    "BRepBuilderAPI_MakeSolid.cpp": [
        "#include <TopoDS_CompSolid.hxx>",
        "#include <TopoDS_Iterator.hxx>",  # 관련 헤더들 추가
        "#include <TopoDS.hxx>"
    ]
}

# 파일을 전처리하여 필요한 헤더를 추가하는 함수
def preprocess_file(file_path):
    basename = os.path.basename(file_path)
    
    # 문제가 있는 파일인지 확인
    for problematic_file, headers in PROBLEMATIC_FILES_HEADERS.items():
        if problematic_file in basename:
            console.print(f"Preprocessing {basename} with additional headers")
            
            # 임시 파일 생성
            with tempfile.NamedTemporaryFile(delete=False, mode='w+', suffix='.cpp') as temp_file:
                # 원본 파일 내용 읽기
                with open(file_path, 'r') as original_file:
                    content = original_file.read()
                
                # 임시 수정 내용 작성
                # 첫 번째 #include 라인 이후에 헤더 삽입
                include_pos = content.find('#include')
                if include_pos != -1:
                    # 첫 번째 #include 라인 끝 찾기
                    next_line_pos = content.find('\n', include_pos)
                    if next_line_pos != -1:
                        # 헤더 삽입
                        new_content = (
                            content[:next_line_pos + 1] + 
                            '\n'.join(headers) + '\n' + 
                            content[next_line_pos + 1:]
                        )
                        temp_file.write(new_content)
                    else:
                        temp_file.write(content)
                else:
                    temp_file.write(content)
                
            return temp_file.name
    
    # 문제가 없는 파일은 원본 경로 반환
    return file_path

# @tryExcept
def buildOneFile(args, item):
    # 파일 전처리
    processed_item = preprocess_file(item)
    
    try:
        return local['ccache']['emcc']([
            *buildOptions,
            *(["-pthread", "-DHAVE_TBB"] if args["threading"] == "multi-threaded" else []),
            *(f"-I{x}" for x in (ocIncludePaths + additionalIncludePaths + [TMP_DIR])),
            "-c",
            processed_item,
            "-o",
            f"{item}.o",
        ])
    finally:
        # 임시 파일이면 삭제
        if processed_item != item:
            try:
                os.unlink(processed_item)
            except:
                pass

def compileCustomCodeBindings(args, file="myMain.h"):
    filesToBuild = []
    for dirpath, _, filenames in os.walk(f"{LIBRARY_BASE_PATH}/{file}"):
        filesToBuild.extend(
            map(
                lambda x: f"{dirpath}/{x}",
                filter(
                    lambda x: x.endswith(".cpp")
                    # and x.endswith('OSD_Parallel.cpp')
                    and not os.path.exists(f"{dirpath}/{x}.o"),
                    filenames,
                ),
            )
        )

    console.print(f"Building {len(filesToBuild)} files")

    func = delayed(buildOneFile)
    parallel = ParallelProgress(n_jobs=-1, backend="threading")
    futures = []

    target = sorted(filesToBuild)

    for item in target:
        if not os.path.exists(f"{item}.o"):
            futures.append(func(args, item))
        else:
            console.print(f"file {item}.o already exists, skipping")

    parallel(futures)



if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        dest="threading",
        choices=["single-threaded", "multi-threaded"],
        help="Build in single vs. multi-threaded mode",
        nargs="*",
        default="single-threaded",
    )
    args = parser.parse_args()

    compileArgs = {"threading": args.threading}

    compileCustomCodeBindings(compileArgs, "")
