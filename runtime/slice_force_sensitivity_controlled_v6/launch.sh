set -o pipefail
source /opt/openfoam10/etc/bashrc
(cd '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/cases/offset_0000' && pimpleFoam > '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/logs/offset_0000.stdout' 2> '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/logs/offset_0000.stderr') & p0=$!
(cd '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/cases/offset_0001' && pimpleFoam > '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/logs/offset_0001.stdout' 2> '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/logs/offset_0001.stderr') & p1=$!
(cd '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/cases/offset_0002' && pimpleFoam > '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/logs/offset_0002.stdout' 2> '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/logs/offset_0002.stderr') & p2=$!
wait $p0; r0=$?
wait $p1; r1=$?
wait $p2; r2=$?
printf 'offset_0000_return=%s\noffset_0001_return=%s\noffset_0002_return=%s\n' $r0 $r1 $r2 > '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/slice_force_sensitivity_controlled_v6/logs/returns.txt'
test $r0 -eq 0 -a $r1 -eq 0 -a $r2 -eq 0
