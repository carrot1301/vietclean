# Benchmark nhẹ

Benchmark không chạy trong CI và không dùng dữ liệu thật. Mỗi lệnh chỉ chạy một workload
để tránh vô tình tạo file 1 triệu dòng:

```bash
python benchmarks/benchmark.py --case dataframe-100k
python benchmarks/benchmark.py --case csv-1m
python benchmarks/benchmark.py --case vietnamese-text
python benchmarks/benchmark.py --case finance-numeric
```

Smoke test nhanh:

```bash
python benchmarks/benchmark.py --case csv-1m --rows 1000
```

Output JSON chỉ chứa tên case, số dòng, thời gian, throughput và peak memory do
`tracemalloc` quan sát. Peak này không bao phủ mọi native allocation của pandas/numpy;
dùng process-level monitor của hệ điều hành khi cần số liệu capacity planning. CSV được
tạo trong temporary directory và tự dọn sau run.

Khi so sánh release, ghi lại VietClean/Python/pandas version, OS/CPU/RAM, command và ít
nhất ba lần chạy. Không commit file CSV benchmark hoặc output có dữ liệu production.
