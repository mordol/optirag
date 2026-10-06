"""PDF 폴더 → opendataloader-pdf(Fast) 1회 호출로 일괄 변환 (.md + .json)
usage: python run_convert.py [PDF_DIR=samples/] [OUT_DIR=output/]"""
import sys, time, opendataloader_pdf

pdf_dir = sys.argv[1] if len(sys.argv) > 1 else "samples/"
out_dir = sys.argv[2] if len(sys.argv) > 2 else "output/"
t = time.perf_counter()
opendataloader_pdf.convert(input_path=[pdf_dir], output_dir=out_dir, format="markdown,json")
print(f"ELAPSED_SEC={time.perf_counter() - t:.2f}")
