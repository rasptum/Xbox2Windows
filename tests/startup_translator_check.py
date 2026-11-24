"""Checks for the startup shader translator (tools/startup/gfx2hlsl.py) that need no game data.

Descriptor offsets: one s_load_dwordx16 from a descriptor table fetches two 8-dword image descriptors.
An image_sample that names the upper one (s[N+8:N+15]) must resolve to byte offset 32 of the table,
not to the start of the load; otherwise both samples bind the same texture.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'startup'))
import gfx2hlsl  # noqa: E402


def stage_with_table():
    stage = gfx2hlsl.Stage.__new__(gfx2hlsl.Stage)  # no machine code: only the scalar symbol state
    stage.sym = {8: ('ptr', ('table', 0))}
    return stage


def check_wide_load(failures):
    stage = stage_with_table()
    stage.op_s_load_dwordx16(['s[24:39]', 's[8:9]', '0x0'], [])
    got = [stage.descriptor('s[24:31]'), stage.descriptor('s[32:39]')]
    want = [(('table', 0), 0), (('table', 0), 32)]
    if got != want:
        failures.append('s_load_dwordx16 descriptors: got %s, expected %s' % (got, want))


def check_offset_load(failures):
    stage = stage_with_table()
    stage.op_s_load_dwordx8(['s[16:23]', 's[8:9]', '0x40'], [])
    got = [stage.descriptor('s[16:19]'), stage.descriptor('s[20:23]')]
    want = [(('table', 0), 0x40), (('table', 0), 0x50)]
    if got != want:
        failures.append('s_load_dwordx8 at +0x40: got %s, expected %s' % (got, want))


def check_negative_control(failures):
    # A key that ignores the register's dword index (the former behaviour) gives the second
    # descriptor offset 0, the same resource as the first: the check above must tell them apart.
    stage = stage_with_table()
    stage.op_s_load_dwordx16(['s[24:39]', 's[8:9]', '0x0'], [])
    first, second = stage.sym[24], stage.sym[32]
    if (first[1], first[2]) != (second[1], second[2]):
        failures.append('negative control: the load no longer records a shared base offset')
    if stage.descriptor('s[32:39]') == (first[1], first[2]):
        failures.append('negative control: the upper descriptor resolves to the load base')


def bare_stage():
    stage = gfx2hlsl.Stage.__new__(gfx2hlsl.Stage)
    stage.sym, stage.lines, stage.used_s, stage.used_v, stage.exec_known, stage.masks = {}, [], set(), set(), True, set()
    return stage


def lower(code_hex):
    """Decodes one instruction (hex bytes as stored) and returns the HLSL lines it emits."""
    ins = gfx2hlsl.decode(bytes.fromhex(code_hex) + bytes.fromhex('000081bf'))  # + s_endpgm
    stage = bare_stage()
    stage.one(ins[0][2], ins[0][3])
    return stage.lines


# Two VOP2 SDWA words measured in a pixel shader: v_and_b32 v8 (v9), constant 63 (scalar flag),
# v2 with a WORD_0 (WORD_1) source select, DWORD destination.
SDWA_WORD0 = 'f9041036bf068604'
SDWA_WORD1 = 'f9041236bf068605'


def check_sdwa(failures):
    got = [lower(SDWA_WORD0), lower(SDWA_WORD1)]
    want = [['v8 = 0x0000003fu & (((v2) >> 0) & 0xffffu);'], ['v9 = 0x0000003fu & (((v2) >> 16) & 0xffffu);']]
    if got != want:
        failures.append('v_and_b32 SDWA: got %s, expected %s' % (got, want))
    # Negative control: the WORD_1 select must not lower like WORD_0 (a decoder that ignores
    # SRC1_SEL would give both the same expression).
    if got[0] and got[1] and got[0][0].split('=', 1)[1] == got[1][0].split('=', 1)[1]:
        failures.append('negative control: WORD_0 and WORD_1 selects lower to the same expression')
    # Refusal: SRC1_NEG set (bit 28 of the extension word) must stop translation, not be dropped.
    word = bytearray(bytes.fromhex(SDWA_WORD0))
    word[7] |= 0x10
    try:
        lower(word.hex())
        failures.append('SDWA with SRC1_NEG was translated instead of refused')
    except gfx2hlsl.Unsupported:
        pass


def check_readfirstlane(failures):
    stage = bare_stage()
    stage.one('v_readfirstlane_b32', 'v_readfirstlane_b32 s16, v11')
    if stage.lines != ['s16 = v11;']:
        failures.append('v_readfirstlane_b32: got %s' % stage.lines)


def main():
    failures = []
    for check in (check_wide_load, check_offset_load, check_negative_control, check_sdwa, check_readfirstlane):
        check(failures)
    for line in failures:
        print('FAIL', line)
    print('startup translator checks: %d failed' % len(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
