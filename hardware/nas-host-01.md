# nas-host-01

## Hardware

- Case
    - [Innovision S45624 with the 12G MiniSAS HD Backplane](https://iovstech.com/4u-server-case/s45624.html) [(Buy)](https://www.aliexpress.us/item/3256804052792939.html?spm=a2g0o.order_list.order_list_main.11.39d11802Y8aRJw&gatewayAdapt=glo2usa)
- Motherboard
    - [Asrock Rack ROMED8-2T](https://www.asrockrack.com/general/productdetail.asp?Model=ROMED8-2T#Specifications)
- CPU
    - [AMD Epyc Rome 7282 (16 Core)](https://en.wikipedia.org/wiki/Epyc#Second_generation_Epyc_(Rome))
- RAM
    - 4x 16 GB DDR4-3200
    - 4x 32 GB DDR4-3200
- [Broadcom 9305-24e](https://docs.broadcom.com/doc/BC00-0392EN)
- 2x [Asus Hyper M.2 x16 Gen 4](https://www.asus.com/us/motherboards-components/motherboards/accessories/hyper-m-2-x16-gen-4-card/)
- [Linkreal 4x U.2 to PCIe x16 Adapter](https://www.aliexpress.us/item/3256803285836696.html?spm=a2g0o.order_list.order_list_main.41.39d11802Y8aRJw&gatewayAdapt=glo2usa)
- [Nvidia T600](https://www.nvidia.com/en-gb/design-visualization/desktop-graphics/#nv-accordion-014abf56a5-item-7ed9a9ec90)
- U.2 Drives
    - [Intel Optane 905P - 960 GB](https://www.intel.com/content/www/us/en/products/sku/147529/intel-optane-ssd-905p-series-960gb-2-5in-pcie-x4-3d-xpoint/specifications.html) [(Buy)](https://www.newegg.com/intel-optane-905p-1-5tb/p/N82E16820167505)
    - [Intel Optane 905P - 1.5 TB](https://www.intel.com/content/www/us/en/products/sku/147526/intel-optane-ssd-905p-series-1-5tb-2-5in-pcie-x4-3d-xpoint/specifications.html) [(Buy)](https://www.newegg.com/intel-optane-ssd-905p-series-960gb/p/N82E16820167463)
    - [HPE VK003840KWWFP (Rebranded SK Hynix PE6011) - 3.84 TB](https://www.techpowerup.com/ssd-specs/sk-hynix-pe6011-3-8-tb.d1490)
- M.2 Drives
    - 4x [Intel Optane P1600X - 118 GB](https://ark.intel.com/content/www/us/en/ark/products/211867/intel-optane-ssd-p1600x-series-118gb-m-2-80mm-pcie-3-0-x4-3d-xpoint.html) [(Buy)](https://www.newegg.com/intel-optane-ssd-p1600x-118gb/p/1Z4-009F-00621?Item=1Z4-009F-00621)
    - 2x [Solidigm P44 Pro - 2 TB](https://www.solidigm.com/products/client/pro-series/p44.html#form=M.2%202280&cap=2%20TB)
    - 2x [Samsung 980 Pro - 2 TB](https://semiconductor.samsung.com/consumer-storage/internal-ssd/980pro/)
- Hard Drives
    - 4x WD Red - 8 TB
    - 3x WD Easystore shucked - 18 TB
    - 1x Seagate Exos X20 (Refurbished) - 18 TB
    - 1x Seagate Exos X18 (Refurbished) - 18 TB
    - 4x WD Easystore shucked - 14 TB
    - 1x Seagate Exos X18 (Refurbished) - 14 TB
    - 2x Seagate Exos X16 (Refurbished) - 14 TB
    - 2x WD Easystore shucked - 12 TB

### Motherboard

I initially had a [Supermicro H12SSL-i](https://www.supermicro.com/en/products/motherboard/H12SSL-i). [However, it has exposed surface mount components for the BMC next to the middle PCIe slots that I damaged with a PCIe bracket when inserting a card.](https://forums.servethehome.com/index.php?threads/h12ssl-i-stuck-at-bmc-initiating.38043/) This kills the BMC, and the BIOS by default won’t boot if the BMC isn’t online. **If you do get this motherboard, immediately disable the option in the BIOS to wait for the BMC before booting and be careful when inserting cards.** _Please learn from my mistake._

### CPU

I chose the 7282 because it has a 120 W TDP vs the comparable 16 core 7302P that has a 155W TDP. It achieves this by only having 2 active CCDs vs the 7302P's 4 CCDs. [However this limits it to 4 memory channels vs 8 memory channels](https://www.servethehome.com/amd-epyc-7002-rome-cpus-with-half-memory-bandwidth/). I value lower power consumption over raw performance, so the trade-off was worth it. Additionally, I chose DDR-3200 RAM (the fastest supported) to try to make up some of the performance.

## Motherboard Layout

The PCIE2 Selection Jumpers are set to PE8_SEL = 1_2 and PE16_SEL = 2_3 which configures:

- PCIE2 runs at x8
- M2_1/SATA_4_7 Enabled
- OCU1/OCU2 Disabled

### M.2

#### M2_1

- Intel Optane P1600X - 118 GB

#### M2_2

- Intel Optane P1600X - 118 GB

### PCIe

Numbering is descending from slot 7 which is closest to the CPU.

#### Slot 7

The end of this had to be trimmed ~0.5 cm to make it fit. I _think_ no traces were cut, but I haven't populated the last U.2 slot to verify...

##### Linkreal 4x U.2 to PCIe x16 Adapter

- Intel Optane 905P - 960 GB
- Intel Optane 905P - 1.5 TB
- HPE VK003840KWWFP (Rebranded SK Hynix PE6011) 3.84 TB

#### Slot 6

##### Asus Hyper M.2 x16 Gen 4

- 2x Intel Optane P1600X - 118 GB

#### Slot 5

##### Asus Hyper M.2 x16 Gen 4

- 2x Solidigm P44 Pro - 2 TB
- 2x Samsung 980 Pro - 2 TB

#### Slot 4

Empty

#### Slot 3

Empty

#### Slot 2

This is configured to be x8.

##### Broadcom 9305-24e

Connected to the case backplane that all of the hard drives are connected to.

#### Slot 1

##### Nvidia T600

## Use

### Host

- Proxmox boot drives - ZFS RAID 1
    - x2 Intel Optane P1600X - 118 GB
- Proxmox storage
    - Intel Optane 905P - 960 GB
    - Intel Optane 905P - 1.5 TB

### nas-01 VM Passthrough

- ZFS Mirror Pool (tank) - 16 TB
    - 4x WD Red 8 TB
    - 2x Intel Optane P1600X - 118 GB as [ZFS mirrored metadata special device](https://forum.level1techs.com/t/zfs-metadata-special-device-z/159954)
- ZFS Mirror Pool (sink) - 4 TB
    - 2x Solidigm P44 Pro - 2 TB
    - 2x Samsung 980 Pro - 2 TB
- Staging/Temp data
    - HPE VK003840KWWFP (Rebranded SK Hynix PE6011) - 3.84 TB
- Snapraid/mergerfs Pool
    - Data Disks
        - 1x WD Easystore shucked - 18 TB
        - 1x Seagate Exos X20 (Refurbished) - 18 TB
        - 1x Seagate Exos X18 (Refurbished) - 18 TB
        - 4x WD Easystore shucked - 14 TB
        - 1x Seagate Exos X18 (Refurbished) - 14 TB
        - 2x Seagate Exos X16 (Refurbished) - 14 TB
        - 2x WD Easystore shucked - 12 TB
    - Parity Disks
        - 2x WD Easystore shucked - 18 TB

### media-01 VM Passthrough

- Transcoding
    - Nvidia T600
