# C0 双角色切换验证

此目录存放本轮重新运行的自动化证据，不覆盖 G0 历史基线。
pytest.xml 为 Python 全量回归；前端实际函数的确定时序测试通过命令
`node scripts/diag/c0_frontend_test.cjs` 重现，不调用云 API 或音频设备。
