# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Known buggy kernel commit SHAs and their later Fixes: commits.

``BUG_TO_FIXES`` is the static ground-truth used by the eval harness.
Regenerate it by running this module as a script:

    python -m tests.eval.bug_commits \
        --kernel-path tests/linux \
        --scope-ref patchwise-linux-next-stable

The discovery function is otherwise unused at run time.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x1f"
_FIXES_LINE_RE = re.compile(r"^Fixes:\s+([0-9a-fA-F]{12,40})\b", re.MULTILINE)


BUG_COMMITS: list[str] = [
    "44dc42d254bf7f0be0c8c4f0361db6452f5ce967",
    "e505edaedcb9e7d16eefddc62d2189afaea0febc",
    "265280b99822e5562eb431b102f2ba773c7b2a0a",
    "144ecf310eb52d9df607b9b7eeb096743e232a96",
    "b1529a41f777a48f95d4af29668b70ffe3360e1b",
    "4f74d2c8e827af12596f153a564c868bf6dbe3dd",
    "e130242dc351f1cfa2bbeb6766a1486ce936ef88",
    "23689e91fb22c15b84ac6c22ad9942039792f3af",
    "81a84182c3430c8f5f7ccf9e95a10b99f727f727",
    "30dad30922ccc733cfdbfe232090cf674dc374dc",
    # mm subsystem
    "7679ba6b36dbb300b757b672d6a32a606499e14b",
    "5b47c02967ab770aa7661c8863a21b2fd59e35ff",
    "d65917c42373f70159a3fc453f8f028fd665e04f",
    "0120dd6e4e202e19a0e011e486fb2da40a5ea279",
    "86039bd3b4e6a1129318cbfed4e0a6e001656635",
    # bpf subsystem
    "1c2a088a6626d4f51d2f2c97b0cbedbfbf3637f6",
    "ab6c637ad0276e42f8acabcbc64932a6d346dab3",
    "e0cea7ce988cf48cc4052235d2ad2550b3bc4fa0",
    "317460317a02a1af512697e6e964298dedd8a163",
    "e54bcde3d69d40023ae77727213d14f920eb264a",
    # net subsystem
    "43a0c6751a322847cb6fa0ab8cbf77a1d08bfc0a",
    "879af96ffd72706c6e3278ea6b45b0b0e37ec5d7",
    "a2cbb1603943281a604f5adc48079a148db5cb0d",
    # tracing subsystem
    "8cf868affdc459beee1a941df0cfaba1673740e3",
    "067fe038e70f6e64960d26a79c4df5f1413d0f13",
    # misc subsystems
    "d6e152d905bdb1f32f9d99775e2f453350399a6a",
    "b46acd6a6a627d876898e1c84d3f84902264b445",
    "ad4ecbcba72855a2b5319b96e2a3a65ed1ca3bfd",
    "900575aa33a3eaaef802b31de187a85c4a4b4bd0",
    "46be1453e6e61884b4840a768d1e8ffaf01a4c1c",
]


# Mapping from buggy commit SHA to its later "Fixes:" commits, scoped to
# patchwise-linux-next-stable and de-duplicated by (subject, diff hash).
# Regenerate with `python -m tests.eval.bug_commits`.
BUG_TO_FIXES: dict[str, list[str]] = {
    "44dc42d254bf7f0be0c8c4f0361db6452f5ce967": [
        "97384a65c5e304ccab0477751546f5519d9371c3",  # dt-bindings: input: iqs7222: Add support for IQS7222A v1.13+
        "99d03b54ef8506771c15deb714396665592f6adf",  # dt-bindings: input: iqs7222: Correct minimum slider size
        "ccad486525c49df2fe2e7090990522547dfd2785",  # dt-bindings: input: iqs7222: Reduce 'linux,code' to optional
        "f0ea452715d72bc365d2b401ceb458f5ae82eeec",  # dt-bindings: input: iqs7222: Extend slider-mapped GPIO to IQS7222C
        "6cfb357851bd3ef0a48e14bccfb5ca6b8104ea61",  # dt-bindings: input: iqs7222: Correct bottom speed step size
        "f5d2c1ed72c26152e6883ed67dc3004a39165098",  # dt-bindings: input: iqs7222: Remove support for RF filter
    ],
    "e505edaedcb9e7d16eefddc62d2189afaea0febc": [
        "8d4c313c03f104c69e25ab03058d8955be9dc387",  # Input: iqs7222 - add support for IQS7222A v1.13+
        "2f6fd232978906f6fb054529210b9faec384bd45",  # Input: iqs7222 - protect against undefined slider size
        "404f3b48e65f058d94429e4a1ec16a1f82ff3b2f",  # Input: iqs7222 - report malformed properties
        "bbd16b0d839978e8c8bec2b9a162373f64fc2fbb",  # Input: iqs7222 - drop unused device node references
        "d56111ed58482de0045e1e1201122e6e71516945",  # Input: iqs7222 - set all ULP entry masks by default
        "514c13b1faed74e9bc19061b6d7c78d53a3402ba",  # Input: iqs7222 - avoid sending empty SYN_REPORT events
        "10e629d31aacb2348a1e9110c31a29e98b31ce38",  # Input: iqs7222 - trim force communication command
        "381932cf61d52bde656c8596c0cb8f46bed53dc0",  # Input: iqs7222 - remove support for RF filter
        "8635c68891c6d786d644747d599c41bdf512fbbf",  # Input: iqs7222 - handle reset during ATI
        "2e70ef525b7309287b2d4dd24e7c9c038a006328",  # Input: iqs7222 - acknowledge reset before writing registers
        "1e4189d8af2749e2db406f92bdc4abccbab63138",  # Input: iqs7222 - protect volatile registers
        "95215d3d19c5b47b8ccef8cb61c9dcd17ac7a669",  # Input: iqs7222 - fortify slider event reporting
        "56a0c54c4c2bdb6c0952de90dd690020a703b50e",  # Input: iqs7222 - correct slider event disable logic
        "66ab05c75642712f382a17a887eb558caa6646e1",  # Input: iqs7222 - avoid dereferencing a NULL pointer
        "eba697b3c30320933aeb19b0606c2099fe880e51",  # Input: iqs7222 - propagate some error codes correctly
    ],
    "265280b99822e5562eb431b102f2ba773c7b2a0a": [
        "d1c5c3e252b8a911a524e6ee33b82aca81397745",  # drm/amd/display: Fixes for dcn32_clk_mgr implementation
        "79b6e265d92092b49252f546e1a0f63ae8851f83",  # drm/amd/display: Fixes for dcn32_clk_mgr implementation
        "c5da61cf5bab30059f22ea368702c445ee87171a",  # drm/amdgpu/display: add missing FP_START/END checks dcn32_clk_mgr.c
        "780f97cec866e1ec6967c66c2a1f68b8aa1e3f23",  # drm/amd/display: Fix __nedf2 undefined for 32 bit compilation
        "202804b9705ce26788c443a54aec47eae20f4596",  # drm/amd/display: Fix __muldf3 undefined for 32 bit compilation
        "071ebbb0d4826ce7c47953b955a522f503dcedfb",  # drm/amd/display: Fix __floatunsidf undefined for 32 bit compilation
        "70f1fcbc83582419fd753701c5abe674e05db785",  # drm/amd/display: Remove unused globals FORCE_RATE and FORCE_LANE_COUNT
    ],
    "144ecf310eb52d9df607b9b7eeb096743e232a96": [
        "045ed31e23aea840648c290dbde04797064960db",  # kfifo: fix kfifo_to_user() return type
    ],
    "b1529a41f777a48f95d4af29668b70ffe3360e1b": [
        "759a7c6126eef5635506453e9b9d55a6a3ac2084",  # ocfs2: fix BUG when iput after ocfs2_mknod fails
    ],
    "4f74d2c8e827af12596f153a564c868bf6dbe3dd": [
        "7f82f922319ede486540e8746769865b9508d2c2",  # mm/mmap.c: fix missing call to vm_unacct_memory in mmap_region
    ],
    "e130242dc351f1cfa2bbeb6766a1486ce936ef88": [
        "000eca5d044d1ee23b4ca311793cf3fc528da6c6",  # mm/mempolicy: fix get_nodes out of bound access
    ],
    "23689e91fb22c15b84ac6c22ad9942039792f3af": [
        "6c2f761dad7851d8088b91063ccaea3c970efe78",  # kasan: fix zeroing vmalloc memory with HW_TAGS
    ],
    "81a84182c3430c8f5f7ccf9e95a10b99f727f727": [
        "0beba407d4585a15b0dc09f2064b5b3ddcb0e857",  # Docs/admin-guide/mm/damon/reclaim: warn commit_inputs vs param updates race
        "205498012513f9a1209d9335bf3766080c587a33",  # Docs/admin-guide/damon/reclaim: remove a paragraph that been obsolete due to online tuning support
    ],
    "30dad30922ccc733cfdbfe232090cf674dc374dc": [
        "ad1ac596e8a8c4b06715dfbd89853eb73c9886b2",  # mm/migration: fix potential pte_unmap on an not mapped pte
    ],
    # mm subsystem
    "7679ba6b36dbb300b757b672d6a32a606499e14b": [
        "ec05f51f1e65bce95528543eb73fda56fd201d94",  # mm/vmalloc: take vmap_purge_lock in shrinker
    ],
    "5b47c02967ab770aa7661c8863a21b2fd59e35ff": [
        "c45b354911d01565156e38d7f6bc07edb51fc34c",  # mm/hugetlb: fix early boot crash on parameters without '=' separator
    ],
    "d65917c42373f70159a3fc453f8f028fd665e04f": [
        "7cf6d940f4032d87d9cfe6b27c0e49e309818e5d",  # mm/sparse: fix preinited section_mem_map clobbering on failure path
    ],
    "0120dd6e4e202e19a0e011e486fb2da40a5ea279": [
        "e3668b371329ea036ff022ce8ecc82f8befcf003",  # zram: do not forget to endio for partial discard requests
    ],
    "86039bd3b4e6a1129318cbfed4e0a6e001656635": [
        "161ce69c2c89781784b945d8e281ff2da9dede9c",  # userfaultfd: allow registration of ranges below mmap_min_addr
    ],
    # bpf subsystem
    "1c2a088a6626d4f51d2f2c97b0cbedbfbf3637f6": [
        "e1d486445af3c392628532229f7ce5f5cf7891b6",  # bpf, arm32: Reject BPF-to-BPF calls and callbacks in the JIT
    ],
    "ab6c637ad0276e42f8acabcbc64932a6d346dab3": [
        "4d0a375887ab4d49e4da1ff10f9606cab8f7c3ad",  # bpf: Fix NULL deref in map_kptr_match_type for scalar regs
    ],
    "e0cea7ce988cf48cc4052235d2ad2550b3bc4fa0": [
        "e5f635edd393aeaa7cad9e42831d397e6e2e1eed",  # bpf: Fix precedence bug in convert_bpf_ld_abs alignment check
    ],
    "317460317a02a1af512697e6e964298dedd8a163": [
        "4fddde2a732de60bb97e3307d4eb69ac5f1d2b74",  # bpf: Fix use-after-free in arena_vm_close on fork
    ],
    "e54bcde3d69d40023ae77727213d14f920eb264a": [
        "1dd8be4ec722ce54e4cace59f3a4ba658111b3ec",  # bpf, arm64: Fix off-by-one in check_imm signed range check
    ],
    # net subsystem
    "43a0c6751a322847cb6fa0ab8cbf77a1d08bfc0a": [
        "fe72340daaf1af588be88056faf98965f39e6032",  # net: strparser: fix skb_head leak in strp_abort_strp()
    ],
    "879af96ffd72706c6e3278ea6b45b0b0e37ec5d7": [
        "1921f91298d1388a0bb9db8f83800c998b649cb3",  # net, bpf: fix null-ptr-deref in xdp_master_redirect() for down master
    ],
    "a2cbb1603943281a604f5adc48079a148db5cb0d": [
        "b025461303d87923abfaae6cc07ba8a83ddfd844",  # tcp: update window_clamp when SO_RCVBUF is set
    ],
    # tracing subsystem
    "8cf868affdc459beee1a941df0cfaba1673740e3": [
        "fad217e16fded7f3c09f8637b0f6a224d58b5f2e",  # tracepoint: balance regfunc() on func_add() failure in tracepoint_add_func()
    ],
    "067fe038e70f6e64960d26a79c4df5f1413d0f13": [
        "5ec1d1e97de134beed3a5b08235a60fc1c51af96",  # tracing: Rebuild full_name on each hist_field_name() call
    ],
    # misc subsystems
    "d6e152d905bdb1f32f9d99775e2f453350399a6a": [
        "4096fd0e8eaea13ebe5206700b33f49635ae18e5",  # clockevents: Add missing resets of the next_event_forced flag
    ],
    "b46acd6a6a627d876898e1c84d3f84902264b445": [
        "0ca0485e4b2e837ebb6cbd4f2451aba665a03e4b",  # fs/ntfs3: validate rec->used in journal-replay file record check
    ],
    "ad4ecbcba72855a2b5319b96e2a3a65ed1ca3bfd": [
        "16c4f0211aaa1ec1422b11b59f64f1abe9009fc0",  # taskstats: set version in TGID exit notifications
    ],
    "900575aa33a3eaaef802b31de187a85c4a4b4bd0": [
        "60a25ef8dacb3566b1a8c4de00572a498e2a3bf9",  # wireguard: device: use exit_rtnl callback instead of manual rtnl_lock in pre_exit
    ],
    "46be1453e6e61884b4840a768d1e8ffaf01a4c1c": [
        "9d317a54e46d3b6420567dc5b63e9d7ff5c064a3",  # platform/x86: hp-wmi: fix fan table parsing
    ],
}


BUG_COMMITS_2: list[str] = [
    "1211907ac0b5f35e5720620c50b7ca3c72d81f7e",
    "c50ca15dd4962bdf834945c2fa29b904042f366a",
    "2964f6b816c25ee094df4a143eb5b8828910045f",
    "2a3c79c61539779a09928893518c8286d7774b54",
    "264c285999fce128fc52743bce582468b26e9f65",
    "6789fb99282c0a8e8e84701b7edf456f4a9e71e2",
    "584ec74748e6fea9042dbd4fd516b025fbe38372",
    "7e47389142b8ada66280be71e01a3238751086f0",
    "d6e152d905bdb1f32f9d99775e2f453350399a6a",
    "bf0c571f7feb6fa05a512e2a5e50702501849d61",
    "9bfa52dac27a20b43bcb73e56dc45aba6b9aaff1",
    "46be1453e6e61884b4840a768d1e8ffaf01a4c1c",
    "abed23c3c44f565dc812563ac015be70dd61e97b",
    "65d657d806848add1e1f0632562d7f47d5d5c188", # sonnet completed above
    "4f55a85cd4fc988712965f710ba1475e7ba3292a",
    "a2225b6e834a838ae3c93709760edc0a169eb2f2", 
# gpt-5.5 errored out here:
#   Traceback (most recent call last):
#   File "/local/mnt/workspace/DEV/patchwise/tests/eval/test_eval_2.py", line 111, in <module>
#     run_pipeline(
#   File "/local/mnt/workspace/DEV/patchwise/tests/eval/run.py", line 135, in run_pipeline
#     review_file = run_aicodereview(
#   File "/local/mnt/workspace/DEV/patchwise/tests/eval/run_aicodereview.py", line 74, in run_aicodereview
#     for line in process.stdout:
#   File "/usr/lib/python3.10/codecs.py", line 322, in decode
#     (result, consumed) = self._buffer_decode(data, self.errors, final)
# UnicodeDecodeError: 'utf-8' codec can't decode byte 0x89 in position 1339: invalid start byte
    "630fbc6e870eb06c5126cc97a3abecbe012272c8",
    "3ac7ea91f3d0442caf6b079e1ddc80e06b079ff9",
    "5b8ffd63fbd94fe71f1baf50a55e31be54a97ca9",
    "32f54f2bbccfdeff81d930d18ccf3161a1c203b9",
    "6f1a9140ecda3baba3d945b9a6155af4268aafc4",
    "38c322068a26a01d7ff64da92179e68cdde9860b",
    "5920d046f7ae3bf9cf51b9d915c1fff13d299d84", # sonnet 4.6 2nd run completed till above: request timed out because ctx window exceeded
    # This commit for sonnet 4.6 reviewed with 17 max_iterations
    "28b7c5a6db74e9305c6cbcbe52f259ff1cf85158", # sonnet 14 Iterations
    "e1d9a66889867c232657a9b6f25d451d7c3ab96f",
    "34abd408c8ba24d7c97bd02ba874d8c714f49db1",
    # --- expanded set (74 newest from 2026-03-01 window) ---
    "2c167d91775b0928eba1d2b9b5483ede63ca7b2e",
    "48103896053828a8b4d25839a39aa8514071914a",
    "d04686d9bc86432ea3008d5f358373d8466d1943",
    "23b3b6f0b584b70a427d5bb826d320151890d7da",
    "b6a57912854e7ea36f3b270032661140cc4209cd",
    "0b8757b220f94421bd4ff50cce03886387c4e71c",
    "444e2a19d7fd1f08044a68fbd8b37721c6531565",
    "9826035a75da609ac2424c97915d6fe5b836ee65",
    "340bdf984613c4a9241d678915e513824f5a9b19",
    "a4f61f0a1afdb3c07025b91379f5c46dd89eb817",
    "4e53116437e919c4b9a9d95fb73ae14fe0cfc8f9",
    "c67c248ca406a86cf8b20bf1b3af5e7f3e36581f",
    "fec114a98b8735ee89c75216c45a78e28be0f128",
    "92258b5bf1ec10204c23a793793a65dc92d17014",
    "e30ca6dd5345c5b8ba05f346a8e81105352fe571",
    "faeea8bbf6e958bf3c00cb08263109661975987c",
    "24b2e73f9700e0682575feb34556b756e59d4548",
    "b2129a39511b71b5ed0ae923d6eebd9398c6184e",
    "1c18a1212c772b6a19e8583f2fca73f3a47b60fd",
    "03ae0a0d0973b9e584a05136aab08fee2ef8e455",
    "3f736aecbdc8e4faf2ed82c981812a6bfc76ea98",
    "514aac3599879a7ed48b7dc19e31145beb6958ac",
    "6e39ba4e5a82aa5469b2ac517b74a71accb0540f",
    "cef2842c922cb762e9cca7bb26b9ef06ef090b52",
    "40014493cece72a0be5672cd86763e53fb3ec613",
    "81ebd43cc0d6d106ce7b6ccbf7b5e40ca7f5503d",
    "a17871778ee28e4df054521e966e9f37c61f541b",
    "a88831502c8f0530e1390a5f704fbc5e73f19b8c",
    "0da18c2dd1cc2a026416222ed206e2f269edf055",
    "46df585fcff7a0de75c3752becc451934927db29",
    "d7db259bd6df56f9540ef92535a5c709b375c4d5",
    "90c5def10bea574b101b7a520c015ca81742183f",
    "e0fcae27ff572212c39b1078e7aa0795ce5970e7",
    "19d6c5b8044366c88c1b1f6e831c0661ff1ddd20",
    "bade44fe546212e142befb69ba22f34944030a99",
    "6bf36c68b0a23afba108920d21c1c108f83371d6",
    "175b45ed343a9c547b5f45293d3ea08d38a7b6f4",
    "0eb707bbc7fc0b42601560e4fea0698d956a7a9a",
    "d1e59a46973719e458bec78d00dd767d7a7ba71f",
    "a319d0c8c8cede3b63538c9f111f84651d078bf6",
    "4d9b262031ffef203243e53577a90ae6e1090e67",
    "1b164b876c36c3eb5561dd9b37702b04401b0166",
    "7671f4949a6c9111234fdbcd577b227ace799f16",
    "5394396ff5488f007248727988b722c5d4f0638b",
    "7803501e5754dc4b295ab22b20562e2b965358ba",
    "966a08c293cb9290d3fe932961404e87b3f81327",
    "c24bb00cc6cfef4afe71de8b9bb5c809a49888f2",
    "8f1de51f49be692de137c8525106e0fce2d1912d",
    "fd78e2b582a05ff3217016bed9c8a3cc632ee61b",
    "710abda58055ed5eaa8958107633cc12a365c328",
    "970bd2dced35632ce1c9e38943354d5389d80ca0",
    "2197cecdb02c57b08340059452540fcf101fa30d",
    "453b8fb68f3641fea970db88b7d9a153ed2a37e8",
    "ade00a6c903f85031061b4e1a45e789b210f9055",
    "5aefaf11f9af5d58257ad3d0c71c447a41963069",
    "9491c63b6cd7bdae97cd29c7c6bf400adbd3578f",
    "f4d37c7c35769579c51aa5fe00161c690b89811d",
    "933e5288fa9714085e384a3d6ad6dcce8089a6b9",
    "4d591252bacb2d004b7c7f5db439bfa23b552ee7",
    "8f1fbe2fd279240d6999e3a975d0a51d816e080a",
    "a258a383b91774ac646517ec1003a442964d8946",
    "2808a8337078f2a65f1f1176880e1491a3e88fa8",
    "7b6d3255e7f8c6df2d21504c47808e3ce84649ac",
    "cbd8c958be54abdf2c0f9b9c3eac971428b9d4b1",
    "587bb3e56a2c37bbd58efff24e56fe7dae472199",
    "7d9351435ebba08bbb60f42793175c9dc714d2fb",
    "d2d8c17ac01a1b1f638ea5d340a884ccc5015186",
    "45c77d4bf8d4d15453d709b9b828e498898e0751",
    "8e8e23dea43e64ddafbd1246644c3219209be113",
    "b520c4eef83dd406591431f936de0908c3ed7fb9",
    "6bee098b91417654703e17eb5c1822c6dfd0c01d",
    "8333f22e44a972428a4e1b5c6a92e3e774e8ac99",
    "854587e69ef3b7a14b4380d9b99e18693bb9a07b",
    "24fbd3967f3fdaad5f93e0d35ae870ed25fb2c3a",
] # gpt-5.4 completed all

BUG_TO_FIXES_2: dict[str, list[str]] = {
    "1211907ac0b5f35e5720620c50b7ca3c72d81f7e": [
        "b4e07588e743c989499ca24d49e752c074924a9a",  # tracing: tell git to ignore the generated 'undefsyms_base.c' file
    ],
    "c50ca15dd4962bdf834945c2fa29b904042f366a": [
        "3d3544a6c996e88bb793bb6b2665c3e3f674f5eb",  # mm/vma: remove __vma_check_mmap_hook()
    ],
    "2964f6b816c25ee094df4a143eb5b8828910045f": [
        "83ef26f911432d9c98b6d8b6ed0709a8b79cd834",  # selftests: Fix duplicated test number reporting
        "df410ad40ca0a57c46c06de2b992de8baf3a7f5a",  # selftests: Fix runner.sh for non-bash shells
        "93edbf1782afaf907b035010c00e7390c9d45b18",  # selftests: Fix runner.sh busybox support
    ],
    "2a3c79c61539779a09928893518c8286d7774b54": [
        "4d5bbbafc170eb21474a37d844211fce6b0f3c51",  # arm_mpam: resctrl: Make resctrl_mon_ctx_waiters static
    ],
    "264c285999fce128fc52743bce582468b26e9f65": [
        "67c0a487efa542cca9477ea84915db2e091f98d0",  # arm_mpam: resctrl: Fix the check for no monitor components found
    ],
    "6789fb99282c0a8e8e84701b7edf456f4a9e71e2": [
        "f758340da529ccb12531c3f83d5992e912f6c8d5",  # arm_mpam: resctrl: Fix MBA CDP alloc_capable handling on unmount
    ],
    "584ec74748e6fea9042dbd4fd516b025fbe38372": [
        "9091e3b59f2bef11c0a841096327565ae0ca220b",  # RDMA/core: Fix user CQ creation for drivers without create_cq
    ],
    "7e47389142b8ada66280be71e01a3238751086f0": [
        "cad6f32665cbff8e556a1da035e55261f7374ebd",  # selftests: Deescalate error reporting
    ],
    "d6e152d905bdb1f32f9d99775e2f453350399a6a": [
        "4096fd0e8eaea13ebe5206700b33f49635ae18e5",  # clockevents: Add missing resets of the next_event_forced flag
    ],
    "bf0c571f7feb6fa05a512e2a5e50702501849d61": [
        "ecdd4fd8a54ca4679ab8676674a2388ea37eee1a",  # bpf: fix arg tracking for imprecise/multi-offset BPF_ST/STX
    ],
    "9bfa52dac27a20b43bcb73e56dc45aba6b9aaff1": [
        "8901ac9d2c7eb8ed7ae5e749bf13ecb3b6062488",  # printf: Compile the kunit test with DISABLE_BRANCH_PROFILING DISABLE_BRANCH_PROFILING
    ],
    "46be1453e6e61884b4840a768d1e8ffaf01a4c1c": [
        "9d317a54e46d3b6420567dc5b63e9d7ff5c064a3",  # platform/x86: hp-wmi: fix fan table parsing
    ],
    "abed23c3c44f565dc812563ac015be70dd61e97b": [
        "680b961ebf41a7183389edbbfd5bbb302f69cce7",  # arm64/hwcap: Include kernel-hwcap.h in list of generated files
    ],
    "65d657d806848add1e1f0632562d7f47d5d5c188": [
        "e254ffb9502c8b4c7f8712c34ae6590796825260",  # selftests/net: Split netdevsim tests from HW tests in nk_qlease
    ],
    "4f55a85cd4fc988712965f710ba1475e7ba3292a": [
        "a1ed2ec1c5458b4a99765439cb595dd0e026a352",  # ALSA: usb-audio: Fix missing error handling for get_min_max*()
    ],
    "a2225b6e834a838ae3c93709760edc0a169eb2f2": [
        "5b484311507b5d403c1f7a45f6aa3778549e268b",  # driver core: Add kernel-doc for DEV_FLAG_COUNT enum value
    ],
    "630fbc6e870eb06c5126cc97a3abecbe012272c8": [
        "46c862f5419e0a86b60b9f9558d247f6084c99f9",  # ALSA: hda/realtek - fixed speaker no sound update
    ],
    "3ac7ea91f3d0442caf6b079e1ddc80e06b079ff9": [
        "660c09404cdabfe969d58375e990d2955af59797",  # selftests/fsmount_ns: add missing TARGETS and fix cap test
        "a27e4642629381ed36d7e22d5b6fff5792ec31f6",  # selftests/statmount: remove duplicate wait_for_pid()
    ],
    "5b8ffd63fbd94fe71f1baf50a55e31be54a97ca9": [
        "d38aa6cdee8e09d77ce3a6c5b04800fb3b146d69",  # selftests/empty_mntns: fix wrong CLONE_EMPTY_MNTNS hex value in comment
    ],
    "32f54f2bbccfdeff81d930d18ccf3161a1c203b9": [
        "1a398a23787506360b4c766270de00abf51b27c8",  # selftests/empty_mntns: fix statmount_alloc() signature mismatch
    ],
    "6f1a9140ecda3baba3d945b9a6155af4268aafc4": [
        "2cd7e6971fc2787408ceef17906ea152791448cf",  # sctp: disable BH before calling udp_tunnel_xmit_skb()
    ],
    "38c322068a26a01d7ff64da92179e68cdde9860b": [
        "a47306a74c31557b1e5cab54642950bbb20294cb",  # ALSA: usb-audio: Exclude Scarlett 18i20 1st Gen from SKIP_IFACE_SETUP
    ],
    "5920d046f7ae3bf9cf51b9d915c1fff13d299d84": [
        "76af54648899abbd6b449c035583e47fd407078a",  # workqueue: validate cpumask_first() result in llc_populate_cpu_shard_id()
    ],
    "28b7c5a6db74e9305c6cbcbe52f259ff1cf85158": [
        "81f971c6abec59240e2bcfc38756bda8172fa788",  # Bluetooth: btmtk: hide unused btmtk_mt6639_devs[] array
    ],
    "e1d9a66889867c232657a9b6f25d451d7c3ab96f": [
        "15bf35a660eb82a49f8397fc3d3acada8dae13db",  # Bluetooth: L2CAP: Fix printing wrong information if SDU length exceeds MTU
    ],
    "34abd408c8ba24d7c97bd02ba874d8c714f49db1": [
        "84ff995ae826aa6bbcc6c7b9ea569ff67c021d72",  # smb: server: avoid double-free in smb_direct_free_sendmsg after smb_direct_flush_send_list()
    ],
    # --- expanded set ---
    "2c167d91775b0928eba1d2b9b5483ede63ca7b2e": [
        "57205e2dd962d2c0e2093cf9b06dad6ba7737844",  # bpf: Delete unused variable
    ],
    "48103896053828a8b4d25839a39aa8514071914a": [
        "e530b484b70552d6222e2327e311f364724ce616",  # netkit: Don't emit scrub attribute for single device mode
    ],
    "d04686d9bc86432ea3008d5f358373d8466d1943": [
        "0aa72fc37e15974827ceb72c5cf8e57085a29301",  # net: fix reference tracker mismanagement in netdev_put_lock()
    ],
    "23b3b6f0b584b70a427d5bb826d320151890d7da": [
        "36446de0c30c62b9d89502fd36c4904996d86ecd",  # ublk: fix tautological comparison warning in ublk_ctrl_reg_buf
    ],
    "b6a57912854e7ea36f3b270032661140cc4209cd": [
        "8b9a097eb2fc37b486afd81388c693bf3ab44466",  # HID: logitech-dj: fix wrong detection of bad DJ_SHORT output report
    ],
    "0b8757b220f94421bd4ff50cce03886387c4e71c": [
        "c271b0815f45078342bc4e778683c86fdc45fde7",  # ASoC: SDCA: Correct kernel doc for sdca_irq_cleanup()
    ],
    "444e2a19d7fd1f08044a68fbd8b37721c6531565": [
        "9fb0106249ca3e01d60c15d4f5592cd58a9164b0",  # drm/ttm/tests: Remove checks from ttm_pool_free_no_dma_alloc
        "3b053cd71598f7769f41b4f01f4540aab2e77b93",  # drm/ttm/tests: fix lru_count ASSERT
    ],
    "9826035a75da609ac2424c97915d6fe5b836ee65": [
        "7fe21f1ef74f2f4b95896789db656c84b22f01c1",  # pinctrl: qcom: sdm670-lpass-lpi: label variables as static
    ],
    "340bdf984613c4a9241d678915e513824f5a9b19": [
        "71934b9e6f36b1786bd969c0e1d2de8f9bd65f0f",  # net: dsa: mxl862xx: don't skip early bridge port configuration
    ],
    "a4f61f0a1afdb3c07025b91379f5c46dd89eb817": [
        "71ba9a5cb125998a875e3f008cbb28b028b609aa",  # sched_ext: Documentation: improve accuracy of task lifecycle pseudo-code
    ],
    "4e53116437e919c4b9a9d95fb73ae14fe0cfc8f9": [
        "0b8757b220f94421bd4ff50cce03886387c4e71c",  # ASoC: SDCA: Unregister IRQ handlers on module remove
    ],
    "c67c248ca406a86cf8b20bf1b3af5e7f3e36581f": [
        "0b30c1037a6a48a4c293d45c6cbe8e312633782f",  # hwmon: (yogafan) various markup improvements
        "6d50ae25666d5433108b1cd11965c0f53c355a83",  # hwmon: (yogafan) fix markup warning
    ],
    "fec114a98b8735ee89c75216c45a78e28be0f128": [
        "20a8e451ec1c7e99060b1bbaaad03ce88c39ddb8",  # bcache: fix uninitialized closure object
    ],
    "92258b5bf1ec10204c23a793793a65dc92d17014": [
        "e6ef4eb871ed884f5f480579b2e5f4fc9d2cb003",  # powerpc32/bpf: fix loading fsession func metadata using PPC_LI32
    ],
    "e30ca6dd5345c5b8ba05f346a8e81105352fe571": [
        "679343977588781bd3effba79e9644aee4ee046c",  # cpufreq/amd-pstate: Add POWER_SUPPLY select for dynamic EPP
    ],
    "faeea8bbf6e958bf3c00cb08263109661975987c": [
        "65782b2db7321d5f97c16718c4c7f6c7205a56be",  # net/sched: cls_fw: fix NULL dereference of "old" filters before change()
    ],
    "24b2e73f9700e0682575feb34556b756e59d4548": [
        "c6890f36fc49848c61d2113a3442eb1b59e0bc4b",  # workqueue: avoid unguarded 64-bit division
    ],
    "b2129a39511b71b5ed0ae923d6eebd9398c6184e": [
        "d5759519805c54786c00765ca1303e6d7a0676ca",  # x86/alternative: delay freeing of smp_locks section
    ],
    "1c18a1212c772b6a19e8583f2fca73f3a47b60fd": [
        "ebfaf2bcc1902d293ed25f5a0580c96f73c47cbb",  # iommu/vt-d: Restore IOMMU_CAP_CACHE_COHERENCY
    ],
    "03ae0a0d0973b9e584a05136aab08fee2ef8e455": [
        "6b0567dc4c9ad140044400e06dd97fdce12c204f",  # platform/x86: uniwill-laptop: Fix signedness bug
    ],
    "3f736aecbdc8e4faf2ed82c981812a6bfc76ea98": [
        "b4464d8f313f903ba72db06042f3958a9a1e464a",  # power: sequencing: pcie-m2: add SERIAL_DEV_BUS dependency
        "19b8c8fc83f755cd52a2aa3dbdb091234592252e",  # power: sequencing: pcie-m2: enforce PCI and OF dependencies
    ],
    "514aac3599879a7ed48b7dc19e31145beb6958ac": [
        "656121b155030086b01cfce9bd31b0c925ee6860",  # net: airoha: Add missing RX_CPU_IDX() configuration in airoha_qdma_cleanup_rx_queue()
    ],
    "6e39ba4e5a82aa5469b2ac517b74a71accb0540f": [
        "9266b4da051a410d9e6c5c0b0ef0c877855aa1b8",  # cpufreq: Allocate QoS freq_req objects with policy
    ],
    "cef2842c922cb762e9cca7bb26b9ef06ef090b52": [
        "973403ca3553f0367a6982687f5f0ee4212e9ab9",  # RDMA/core: Fix memory free for GID table
    ],
    "40014493cece72a0be5672cd86763e53fb3ec613": [
        "3ddbea7542ae529c1a88ef9a8b1ce169126211f6",  # vt: resize saved unicode buffer on alt screen exit after resize
    ],
    "81ebd43cc0d6d106ce7b6ccbf7b5e40ca7f5503d": [
        "2c863dbbeac7b919d4634ad886978a6731916de3",  # usb: gadget: f_hid: Add missing error code
    ],
    "a17871778ee28e4df054521e966e9f37c61f541b": [
        "cee10a01e286e88e0949979e91231270ca9fdb8e",  # net: macb: fix use of at91_default_usrio without CONFIG_OF
    ],
    "a88831502c8f0530e1390a5f704fbc5e73f19b8c": [
        "0e0ffbcd0e8ef7a6919be5ff240b170f596815ca",  # gpu: nova-core: falcon: pad firmware DMA object size to required block alignment
    ],
    "0da18c2dd1cc2a026416222ed206e2f269edf055": [
        "31183edd9cb3465af5c8b9cb16f42259cbf27109",  # ALSA: usb-audio: tidy up the AF16Rig quirks
    ],
    "46df585fcff7a0de75c3752becc451934927db29": [
        "9eccdd38fb50b0fab24dd29497e50d0c0425cc84",  # bpf: Fix block device hooks names
    ],
    "d7db259bd6df56f9540ef92535a5c709b375c4d5": [
        "590204185d84635961b0ce2460784749c959a9b4",  # HID: core: do not allow parsing 0-sized reports
    ],
    "90c5def10bea574b101b7a520c015ca81742183f": [
        "7e0548525abd2bff9694e016b6a469ccd2d5a053",  # iommu: Ensure .iotlb_sync is called correctly
    ],
    "e0fcae27ff572212c39b1078e7aa0795ce5970e7": [
        "d3689cd02c5de52ff5f3044169c482aee0dd5a78",  # irqchip/renesas-rzg2l: Clear the shared interrupt bit in rzg2l_irqc_free()
    ],
    "19d6c5b8044366c88c1b1f6e831c0661ff1ddd20": [
        "3ffe5eb4a5f248c0d4b849f050af973396656f85",  # KVM: s390: vsie: Fix races with partial gmap invalidations
    ],
    "bade44fe546212e142befb69ba22f34944030a99": [
        "8053f49fed581c40fcc87fa54904f4fa473f46b7",  # tracing: Remove duplicate latency_fsnotify() stub
        "724d197aaea19e4f2012fca5b0e30ae690458de3",  # tracing: Remove tracing_alloc_snapshot() when snapshot isn't defined
    ],
    "6bf36c68b0a23afba108920d21c1c108f83371d6": [
        "ea70239320394266ec8ccf43ff3a6415e43b8163",  # tools/sched_ext: Remove redundant SCX_ENQ_IMMED compat definition
    ],
    "175b45ed343a9c547b5f45293d3ea08d38a7b6f4": [
        "61bbcfb50514a8a94e035a7349697a3790ab4783",  # srcu: Push srcu_node allocation to GP when non-preemptible
    ],
    "0eb707bbc7fc0b42601560e4fea0698d956a7a9a": [
        "502455d8bef2f8502540102218c47fc12da2a04e",  # drm/msm/dpu: eliza: Use Eliza-specific CWB array
    ],
    "d1e59a46973719e458bec78d00dd767d7a7ba71f": [
        "6a539eee855cbfe9c32507c70003b7710604fcfb",  # tcp: tcp_vegas: use tcp_vegas_cwnd_event_tx_start()
    ],
    "a319d0c8c8cede3b63538c9f111f84651d078bf6": [
        "e9abf1da0af3f787a03b249945e5ca726c1b8013",  # net: dsa: mxl862xx: cancel pending work on probe error
    ],
    "4d9b262031ffef203243e53577a90ae6e1090e67": [
        "43cec30c44764c4b1401fdeb48bfd18c3fc7eff8",  # tracefs: Removed unused 'ret' variable in eventfs_iterate()
    ],
    "1b164b876c36c3eb5561dd9b37702b04401b0166": [
        "4c56a8ac6869855866de0bb368a4189739e1d24f",  # cgroup: Fix cgroup_drain_dying() testing the wrong condition
    ],
    "7671f4949a6c9111234fdbcd577b227ace799f16": [
        "4a0fc189859bb564fddded12752e1893ad318263",  # gpio: gpio-by-pinctrl: s/used to do/is used to do/
    ],
    "5394396ff5488f007248727988b722c5d4f0638b": [
        "47f06ebbe8dad695002e5d9a2ab436411f88e985",  # perf/arm-cmn: Fix resource_size_t printk specifier in arm_cmn_init_dtc()
        "d49802b6617b96f55d4b61fed81f4cc43858ed3f",  # perf/arm-cmn: Fix incorrect error check for devm_ioremap()
    ],
    "7803501e5754dc4b295ab22b20562e2b965358ba": [
        "af475c16bc02a08ed6af6ca0c920f98a45611fe6",  # gpio: fix up CONFIG_OF dependencies
    ],
    "966a08c293cb9290d3fe932961404e87b3f81327": [
        "88bdac5443e5269bb39c4968d5ee0becbffe3f82",  # dt-bindings: display/msm: qcm2290-mdss: Fix missing ranges in example
    ],
    "c24bb00cc6cfef4afe71de8b9bb5c809a49888f2": [
        "c34cb0d8247458ead7184547220dbc6d285fb4e3",  # drm/amd/display: Add update_descriptor param info in 'update_planes_and_stream_state'
    ],
    "8f1de51f49be692de137c8525106e0fce2d1912d": [
        "62f553d60a801384336f5867967c26ddf3b17038",  # drm/amdgpu: fix the idr allocation flags
        "ea56aa2625708eaf96f310032391ff37746310ef",  # drm/amdgpu: fix the idr allocation flags
    ],
    "fd78e2b582a05ff3217016bed9c8a3cc632ee61b": [
        "52957cdad30f8011da1f4ef1338ba0339ca4c158",  # mmc: sdhci-msm: Fix the wrapped key handling
    ],
    "710abda58055ed5eaa8958107633cc12a365c328": [
        "310a4a9cbb17037668ea440f6a3964d00705b400",  # gpio: shared: shorten the critical section in gpiochip_setup_shared()
    ],
    "970bd2dced35632ce1c9e38943354d5389d80ca0": [
        "1cc96e0e20489159398009d2f453e59c10e413c9",  # libbpf: Fix BTF handling in bpf_program__clone()
    ],
    "2197cecdb02c57b08340059452540fcf101fa30d": [
        "63f500c32a37d490ec623a3130e488cdb9bd6cf7",  # sched_ext: Guard cpu_smt_mask() with CONFIG_SCHED_SMT
    ],
    "453b8fb68f3641fea970db88b7d9a153ed2a37e8": [
        "cd7e1fef5a1ca1c4fcd232211962ac2395601636",  # xen/privcmd: unregister xenstore notifier on module exit
    ],
    "ade00a6c903f85031061b4e1a45e789b210f9055": [
        "c636ae346d196b71e972188f91b3260ae522ade6",  # accel/ivpu: Trigger recovery on TDR with OS scheduling
    ],
    "5aefaf11f9af5d58257ad3d0c71c447a41963069": [
        "be46a408f376df31762e8a9914dc6d082755e686",  # KVM: arm64: Correctly plumb ID_AA64PFR2_EL1 into pkvm idreg handling
    ],
    "9491c63b6cd7bdae97cd29c7c6bf400adbd3578f": [
        "06c85b58e0b13e67f4e56cbba346201bfe95ad00",  # KVM: arm64: Move GICv5 timer PPI validation into timer_irqs_are_valid()
        "fbcbf259d97d340376a176de20bdc04687356949",  # KVM: arm64: Remove evaluation of timer state in kvm_cpu_has_pending_timer()
        "8fe30434a81d36715ab83fdb4a5e6c967d2e3ecf",  # KVM: arm64: Kill arch_timer_context::direct field
    ],
    "f4d37c7c35769579c51aa5fe00161c690b89811d": [
        "848fa8373a53b0e5d871560743e13278da56fabc",  # KVM: arm64: vgic-v5: Correctly set dist->ready once initialised
    ],
    "933e5288fa9714085e384a3d6ad6dcce8089a6b9": [
        "a4a645584793dbbb4e5a1a876800654a8883326e",  # KVM: arm64: vgic-v5: Make the effective priority mask a strict limit
        "42d7eac8291d2724b3897141ab2f226c69b7923e",  # KVM: arm64: vgic-v5: Cast vgic_apr to u32 to avoid undefined behaviours
    ],
    "4d591252bacb2d004b7c7f5db439bfa23b552ee7": [
        "170a77b4185a87cc7e02e404d22b9bf3f9923884",  # KVM: arm64: vgic-v5: Transfer edge pending state to ICH_PPI_PENDRx_EL2
    ],
    "8f1fbe2fd279240d6999e3a975d0a51d816e080a": [
        "e63d0a32e7368f3eb935755db87add1bf000ea90",  # KVM: arm64: vgic-v5: Hold config_lock while finalizing GICv5 PPIs
    ],
    "a258a383b91774ac646517ec1003a442964d8946": [
        "f4626281c6bb563ef5ad9d3a59a1449b45a3dc30",  # KVM: arm64: Don't advertises GICv3 in ID_PFR1_EL1 if AArch32 isn't supported
        "76efe94b1c5cc9b5fac7c5c1096d03f1596c7267",  # KVM: arm64: Fix writeable mask for ID_AA64PFR2_EL1
        "ecc7f02499544ae879716be837af78260a6a10f7",  # KVM: arm64: vgic: Don't reset cpuif/redist addresses at finalize time
    ],
    "2808a8337078f2a65f1f1176880e1491a3e88fa8": [
        "77acae60be60adddf33e4c7e9cf73291f64fb9e8",  # arm64: Fix field references for ICH_PPI_DVIR[01]_EL2
    ],
    "7b6d3255e7f8c6df2d21504c47808e3ce84649ac": [
        "0a42ca4d2bff6306dd574a7897258fd02c2e6930",  # scsi: bsg: fix buffer overflow in scsi_bsg_uring_cmd()
    ],
    "cbd8c958be54abdf2c0f9b9c3eac971428b9d4b1": [
        "d82d09d5ba4be0b5eb053b2ba2bc0e82c49cf2c8",  # KVM: arm64: Don't skip per-vcpu NV initialisation
    ],
    "587bb3e56a2c37bbd58efff24e56fe7dae472199": [
        "6a01b9f0a5ec38112db54370ce7794db2be5a5de",  # iommu/arm-smmu-v3: Do not continue in __arm_smmu_domain_inv_range()
    ],
    "7d9351435ebba08bbb60f42793175c9dc714d2fb": [
        "57a04a13aac1f247d171c3f3aef93efc69e6979e",  # netdevsim: fix build if SKB_EXTENSIONS=n
    ],
    "d2d8c17ac01a1b1f638ea5d340a884ccc5015186": [
        "5a1140404cbf7ba40137dfb1fb96893aa9a67d68",  # usb: typec: ucsi: skip connector validation before init
    ],
    "45c77d4bf8d4d15453d709b9b828e498898e0751": [
        "1de647abdfda9dc307503d0a85152161850ba52c",  # drm/i915/psr: Fixes for Dell XPS DA14260 quirk
    ],
    "8e8e23dea43e64ddafbd1246644c3219209be113": [
        "e379dce8af11d8d6040b4348316a499bfd174bfb",  # sched/topology: Fix sched_domain_span()
    ],
    "b520c4eef83dd406591431f936de0908c3ed7fb9": [
        "67807fbaf12719fca46a622d759484652b79c7c3",  # block: fix bio_alloc_bioset slowpath GFP handling
    ],
    "6bee098b91417654703e17eb5c1822c6dfd0c01d": [
        "45ebe43ea00d6b9f5b3e0db9c35b8ca2a96b7e70",  # Revert "drm: Fix use-after-free on framebuffers and property blobs when calling drm_dev_unplug"
    ],
    "8333f22e44a972428a4e1b5c6a92e3e774e8ac99": [
        "b6c0783ff278671e38fed978fefb732101ac8836",  # drm/amd/display: Add get_default_tiling_info for dcn42
    ],
    "854587e69ef3b7a14b4380d9b99e18693bb9a07b": [
        "02d0e59e36e06fb728eb4dea8479f502c67b9fbc",  # tcp: use __jhash_final() in inet6_ehashfn()
    ],
    "24fbd3967f3fdaad5f93e0d35ae870ed25fb2c3a": [
        "fe3e54253f0b04ec9e85d46e10aadbdbb31d29b2",  # virtio_net: sync RX buffer before reading the header
    ],
}


def discover_fixes(
    bug_shas: list[str],
    kernel_path: Path,
    scope_ref: str = "patchwise-linux-next-stable",
) -> dict[str, list[str]]:
    """Walk *scope_ref* once and return ``{bug_sha: [fix_sha, ...]}``.

    Used to regenerate ``BUG_TO_FIXES``.  Not called at run time.
    """
    prefix_by_full = {sha[:12].lower(): sha for sha in bug_shas}
    if not prefix_by_full:
        return {}

    grep_pattern = "^Fixes: \\(" + "\\|".join(prefix_by_full.keys()) + "\\)"
    fmt = f"{_FIELD_SEP}%H{_FIELD_SEP}%B{_RECORD_SEP}"

    result = subprocess.run(
        ["git", "-C", str(kernel_path), "log", scope_ref, "-i",
         f"--grep={grep_pattern}", f"--format={fmt}"],
        capture_output=True,
        text=True,
        check=True,
    )

    grouped: dict[str, list[str]] = {full: [] for full in bug_shas}
    for record in result.stdout.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(_FIELD_SEP)
        if len(parts) < 3:
            continue
        sha, body = parts[1], parts[2]
        if not sha:
            continue
        for prefix_match in _FIXES_LINE_RE.findall(body):
            full = prefix_by_full.get(prefix_match[:12].lower())
            if full is not None:
                grouped[full].append(sha)

    return grouped


def _emit_python_literal(mapping: dict[str, list[str]], kernel_path: Path) -> str:
    """Format *mapping* as a Python dict literal with subject comments."""
    lines = ["BUG_TO_FIXES: dict[str, list[str]] = {"]
    for bug, fix_shas in mapping.items():
        lines.append(f'    "{bug}": [')
        for sha in fix_shas:
            subject = subprocess.run(
                ["git", "-C", str(kernel_path), "log", "-1", "--format=%s", sha],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            lines.append(f'        "{sha}",  # {subject}')
        lines.append("    ],")
    lines.append("}")
    return "\n".join(lines)


def _main() -> None:
    p = argparse.ArgumentParser(description="Regenerate BUG_TO_FIXES mapping.")
    p.add_argument("--kernel-path", type=Path, required=True)
    p.add_argument("--scope-ref", default="patchwise-linux-next-stable")
    args = p.parse_args()

    mapping = discover_fixes(BUG_COMMITS, args.kernel_path, scope_ref=args.scope_ref)
    print(_emit_python_literal(mapping, args.kernel_path))


if __name__ == "__main__":
    _main()
