[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [switch]$Apply,
    [string]$ConfirmationPhrase = ''
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$SnapshotId = 'safe-tmp-20260831T164846+0800'
$ClassificationSnapshotAt = '2026-08-31T16:48:46+08:00'
$HashManifestFrozenAt = '2026-08-31T17:10:49+08:00'
$ExpectedFileCount = 283
$ExpectedBytes = [long]29862516
$RequiredConfirmationPhrase = 'DELETE-SAFE-TMP-SNAPSHOT-20260831'

# This immutable manifest is the complete deletion boundary. It intentionally
# excludes every preserve/uncertain item and every file discovered after the
# classification snapshot.
$ManifestJson = @'
[
  {
    "path": ".tmp/0160-prepare.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0161-prepare-32.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0161-prepare-64.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0161-prepare.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0161-registered.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0164-pad0-32.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0164-pad0-64.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0164-prepare.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0167-prepare-32.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0167-prepare-64.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0167-prepare.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0167-registered.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0168-registered.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0169-registered.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0171-pad0-32.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0171-pad0-64.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0171-pad0.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/0171-prepare.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/agents-project-overview.index",
    "length": 855314,
    "sha256": "9aeca1408aa29fe0fec0c044ede04511243c8d4f4a2028c873b291093c217a80",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/art-pck-docs-363b952d.index",
    "length": 878475,
    "sha256": "c6dd9b8f224ba66506f81dfabf1f80d64595e72a2067e56cc78a5ef680fae643",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-final-vivhite-semantics.patch",
    "length": 7883,
    "sha256": "88540421cbfc931676302f958cc9da799f2e58133b91b3cacf9c2950f42e4940",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/brain-native-save-barrier-work/apply-check.index",
    "length": 855731,
    "sha256": "a398550cee9ad72d19b256cf515658494670f53e331793432dd041573ec00913",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-native-save-barrier-work/final-check.index",
    "length": 855731,
    "sha256": "a398550cee9ad72d19b256cf515658494670f53e331793432dd041573ec00913",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-native-save-barrier-work/fresh-check.index",
    "length": 855731,
    "sha256": "a398550cee9ad72d19b256cf515658494670f53e331793432dd041573ec00913",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-native-save-barrier-work/head-apply-check.index",
    "length": 855731,
    "sha256": "a398550cee9ad72d19b256cf515658494670f53e331793432dd041573ec00913",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-native-save-barrier-work/patch-current-head-final.index",
    "length": 855787,
    "sha256": "428b7d2d558fedc39f387d93b3e8b6b460fdc0eccaf07f748fe1a4414173d0d1",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-native-save-barrier-work/patch-current-head-u1.index",
    "length": 855787,
    "sha256": "428b7d2d558fedc39f387d93b3e8b6b460fdc0eccaf07f748fe1a4414173d0d1",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-native-save-barrier-work/patch-current-head.index",
    "length": 855787,
    "sha256": "428b7d2d558fedc39f387d93b3e8b6b460fdc0eccaf07f748fe1a4414173d0d1",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-native-save-barrier-work/patch.index",
    "length": 855787,
    "sha256": "428b7d2d558fedc39f387d93b3e8b6b460fdc0eccaf07f748fe1a4414173d0d1",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-profile-final-20260831.index",
    "length": 856203,
    "sha256": "891141b53e2baa59b105122544543bdbef081851fc8a69e142921f2614f76489",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/brain-test-log-isolation.patch",
    "length": 13430,
    "sha256": "3ef0820bd19381a60060b4f6d260fbafbe5aa0e54c178f305a7148915a9143e4",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/build-deploy-transaction-v3.patch",
    "length": 122573,
    "sha256": "fa00b99195c0142ff39da28950d97a1a3bcc77948017807b39bcf7d3a4addb95",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/d-drive-cleanup-doc.index",
    "length": 855418,
    "sha256": "1a6e9c1e1ef0bc63cf5b60c4422ce907c117fbb84fa15fc2050d206494b6ac22",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/disappeared-run-save-barrier.patch",
    "length": 53111,
    "sha256": "d71f203b9aa39723921f5f3ff1c15d91cb8aadd968c45e73ebe73810e5d7c634",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/energy-compose-vulkan.err.log",
    "length": 0,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "category": "zero-byte-log"
  },
  {
    "path": ".tmp/energy-composite/t0p00-actual-128-rgba.png",
    "length": 20458,
    "sha256": "45b0bd2212c46e8729bbb9cd4a8e8968b518957a93fefc9324f369e3a1b2f4e5",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-black-128.png",
    "length": 19023,
    "sha256": "40656d036ba0dca3820579b7c5da5e217acabf1b1b321556aafc1ef28e531cf4",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-black-32.png",
    "length": 1567,
    "sha256": "0aa93273463cd002597341c6bb121708eb98c227b742807dbc7be2cc6426eb61",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-black-64.png",
    "length": 5306,
    "sha256": "0d26244b263b94b308b8c94dc32dd362f5b2ef0cb0dec28b0e0c4cdf4fb42735",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-game-indigo-128.png",
    "length": 19221,
    "sha256": "362fbdd8a9ed50bfa4ef4e99844210fb7440023e1746dbbccce8084c41c4c874",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-game-indigo-32.png",
    "length": 1740,
    "sha256": "793fad3edc4a1eb93df0ed06309cf88f2a327ed41a92afb0cd6e34bf8d4f0a5c",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-game-indigo-64.png",
    "length": 5568,
    "sha256": "52a406118096ff612410176c9d498bc8ee32a78a556abb0063b1d19a59acab26",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-white-128.png",
    "length": 19528,
    "sha256": "6d4c24b2c1da5037b964a767d8ca3cf0339ff051db2aedc1c5fc61a0b2702bd6",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-white-32.png",
    "length": 1786,
    "sha256": "4a0eb98907820267f445d9abafe22530be86f76251797bfacd4b0e34ceade26b",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p00-white-64.png",
    "length": 5777,
    "sha256": "7310b0ea0bef57045bd0bb4cb9dd5a6399f36043dad7a29255051a59bf360c48",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-actual-128-rgba.png",
    "length": 20543,
    "sha256": "0eee5ce02dff5f5f0ddadd4711bbd1ef82d65e691a5072dd340d1b35e7628770",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-black-128.png",
    "length": 19047,
    "sha256": "72cc8bced814a6d31bb675fdf7692c92139f97c581ed1461e6c0b5f01a342b9b",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-black-32.png",
    "length": 1554,
    "sha256": "0ecfd57f23a1a95e399cdc1b0706006497383d553164fe4571c159d11fa8d369",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-black-64.png",
    "length": 5283,
    "sha256": "c56b352889971b3f31dfc4fdcf297a3ab4dc82a9b62f3fa7c92dee2439fdc400",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-game-indigo-128.png",
    "length": 19276,
    "sha256": "2c6ad9794d2cd0d137c83d1c22e61dbd4c951db5a6eb471cae97856aa4544270",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-game-indigo-32.png",
    "length": 1735,
    "sha256": "df055e88cc4c60c4c5ab10ae6c85f8afaeeb84bd2f50dc2049a2bc92bba4133f",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-game-indigo-64.png",
    "length": 5608,
    "sha256": "bf0d51e5bed3be02beddb3d23bf817ce03f246eb44d09822db32a9c8eecf9503",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-white-128.png",
    "length": 19534,
    "sha256": "220c690dd23fc696bd2699ed31d308ba4c06817aa574869c5e5794e45360659c",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-white-32.png",
    "length": 1813,
    "sha256": "df99cb83afee88fb6e77383fdd1e3232b2aa2a90f621f0267754f59f01af36b7",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p25-white-64.png",
    "length": 5791,
    "sha256": "0c52626e40b58141eb2664310b67ee269bca49d7c2dd0a9f5f12c99cafa843d1",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-actual-128-rgba.png",
    "length": 20583,
    "sha256": "dfb972ec3908b2a981cdffd56627db04f1d4d61be74cc59aefdcfdd42bc31f87",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-black-128.png",
    "length": 19123,
    "sha256": "1b82aaf90d9b2ee3c43c687a44626ea33e867ec63238104dde434856d03d9926",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-black-32.png",
    "length": 1555,
    "sha256": "20832902f4357c4c26cc66831ec2690a4037714dc39e6054dc9622fac95389ae",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-black-64.png",
    "length": 5325,
    "sha256": "1e2aca5890cc9a1a4547031caaf49c24453d3af91637e27aafc139129eaab221",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-game-indigo-128.png",
    "length": 19340,
    "sha256": "e6a403dc399279ae46c9f29a8fce8c391005cdf73daef2849d1e454c3f739ee2",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-game-indigo-32.png",
    "length": 1720,
    "sha256": "45f5185235a7a505224a62277758098a65483823ca10a3decc21aa334ac0e58a",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-game-indigo-64.png",
    "length": 5569,
    "sha256": "e090a60ac7d78e768beabf951af6a722e861e4dc1fc0a45b9a13449d22aa5587",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-white-128.png",
    "length": 19619,
    "sha256": "3aa4b453bf75a39178c45ccfc83fea029c480321f5f6bf45a03b3e916a8d50c4",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-white-32.png",
    "length": 1810,
    "sha256": "d4098a07668b0b1ddeecca3600aeba1a31128d7d39a5afa44f25b1bc26724bd1",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t0p50-white-64.png",
    "length": 5747,
    "sha256": "24d00c47a517f9548bc8c41229340f8e2be8daf28a8d256829428e9f145d7d34",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-actual-128-rgba.png",
    "length": 20654,
    "sha256": "1fada8fcf74af78639a26b7114231034fa2d5d5a69c7b2f5a71b46e04e83403e",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-black-128.png",
    "length": 19159,
    "sha256": "7021e1c1ab741442469d31ff411602a504367d034ac034bae6dd5dfdecb7dd48",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-black-32.png",
    "length": 1573,
    "sha256": "7bbbf99e1507b487588ac4b234555e33c81ecfb7d357f2c0c843e4d36818f784",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-black-64.png",
    "length": 5323,
    "sha256": "b983c46f2d89968ec47160d97a9154584734de0ed6f0f9a15bc14ba45af7ca14",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-game-indigo-128.png",
    "length": 19325,
    "sha256": "0ed02c928786eddd64b64613ca632ccd69cd5c63b1e1c0376f4f77cc3e7a2ba2",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-game-indigo-32.png",
    "length": 1733,
    "sha256": "f01366e1d37c71d6538033f259c35610b150e26e37ecb481c7fa4135ec4e0559",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-game-indigo-64.png",
    "length": 5631,
    "sha256": "5e735f50086128cc8a256b8018cfb5fe2733e82d59a14f25559e38a18c2c8c5b",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-white-128.png",
    "length": 19620,
    "sha256": "ac18ad32ac1bc86540abd0098cf1911a3d63775f9e861c0af0dedeb94f8f5585",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-white-32.png",
    "length": 1817,
    "sha256": "fa9755e2430c10382345733c8f83049f6210788a2b5ebdb560156c7d001af587",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t1p00-white-64.png",
    "length": 5764,
    "sha256": "f9f772957cd79d866fc0c7057912bd12cec365d054ee0463b49712f9031a3abe",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-actual-128-rgba.png",
    "length": 20824,
    "sha256": "f9e769c038fd946267ae81168d827fcc06e74bccd2226ff032c2c26b3f14eff3",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-black-128.png",
    "length": 19269,
    "sha256": "b8e082d35fbbc753b180a6f50aa9d3be35909d68df2e92235f4b9d094e3e2d79",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-black-32.png",
    "length": 1575,
    "sha256": "ac8840d8a4b38641d361689be9057dd4847eda6ca3a8ea7d19400760e0f72d8a",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-black-64.png",
    "length": 5373,
    "sha256": "124abf771975843e960051a941270f3c1f7d80a21f1edbc3bddc8b6934927325",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-game-indigo-128.png",
    "length": 19478,
    "sha256": "362dee8bdc38a286dcb05b056e17b805759710193bdee847a4258637c28dd2fb",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-game-indigo-32.png",
    "length": 1734,
    "sha256": "6ca4e5b8127c1f22ce4f670fa1ac969e2350fa654997e63b53fdf3d0d69da898",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-game-indigo-64.png",
    "length": 5628,
    "sha256": "340f5bbf46a003711254ee0bbd6b5e0fce2431f3879eb04922cba6bac69609d3",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-white-128.png",
    "length": 19793,
    "sha256": "08e65d08a5eb075e2bcca95e8d97f25547bea456da4f0e7d4408bd358b811b1b",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-white-32.png",
    "length": 1789,
    "sha256": "259fafa701395a8dd2496afd3759c1a62800d66130e1a29b470945d20ba1ae94",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t2p00-white-64.png",
    "length": 5815,
    "sha256": "b69ef37af33586f753d4a90d5dc22dd3c29379a323424ee879c9f16ac15e8afc",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-actual-128-rgba.png",
    "length": 20865,
    "sha256": "a4dd320a5ab3b300512fa41f39eaee3d15cec2f0b63feb5c1200a453cb956dbd",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-black-128.png",
    "length": 19329,
    "sha256": "d1c1a5da5a29e9b061c91aa84b1bdce48cf2a3367378315be3278a5272611703",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-black-32.png",
    "length": 1580,
    "sha256": "53cdf7e420d458a44b44550eaa8a5b4ddd1a8ea835731f104ca5e718a1940a61",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-black-64.png",
    "length": 5363,
    "sha256": "0f25596379858440cf4880c11c0cbaafc2aee1157b2e8539ecfcd824b7860f67",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-game-indigo-128.png",
    "length": 19515,
    "sha256": "31098347d8ce48debf5fcb21869b905fb37bddac6f3d1766c8b6a94b1d5aea15",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-game-indigo-32.png",
    "length": 1753,
    "sha256": "56bba4174056f1030b4dd1977d3e4228a12d3ed0862dbb55f3e9d2efabbcfd8e",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-game-indigo-64.png",
    "length": 5630,
    "sha256": "00b541847f369c5a50ac275017d390205693f4676caa31f77accd09994c5476d",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-white-128.png",
    "length": 19816,
    "sha256": "63b2876d43fa54a0b4ca2185a892dfcfbc1fada50fad664df14d013515813292",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-white-32.png",
    "length": 1804,
    "sha256": "ccbf1d6df869100a8c05fcfd58819e735bf8605ab269efeb1866c27e7b77e2c0",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/energy-composite/t3p00-white-64.png",
    "length": 5825,
    "sha256": "2904cc02952afd068e681cfa007faab73e3cf0ee42384c140cb8608eb6704e6d",
    "category": "committed-energy-composite"
  },
  {
    "path": ".tmp/f9-docs.index",
    "length": 855314,
    "sha256": "a243031860b7400c600a10e1a05d7e113c0bd74d591ae613ada7729f24b54825",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/f9-learning-isolation-task.patch",
    "length": 44638,
    "sha256": "1a3823ccdc02a55df3b8204426550bf5bb60bb9b6baff21ac6681612f0d9b103",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/f9-learning-isolation.index",
    "length": 855314,
    "sha256": "8622fd9a1782c4deef2b2b4b3d0cca344732bf7b8ad9753e70d99c4f8ec3c7f2",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/__main__.py",
    "length": 240,
    "sha256": "2f4b8482e9d979b791a973a412bd1a61bfb725080c8162fdd6b95a70d610a5fa",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/agent.py",
    "length": 178165,
    "sha256": "1c083c19352d6e987556b7051f07ea0325276befa1aef131c9029210442a5e1f",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/AGENTS.md",
    "length": 2519,
    "sha256": "a64f8328a99da7b3184dd130f84f0a1c37b0eae3a285e612a731e5c530dd0399",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/autogit.py",
    "length": 70806,
    "sha256": "18fd6175af304a3cb6077fdae0e085c03ee3d9e65b7f669526ff764e751bef46",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/broadcast_window_patrol.py",
    "length": 7303,
    "sha256": "89f649a93ef6efe01f8e6bf74c9b6e34552f404e352a596ce084d7d64179119a",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/character_profiles.py",
    "length": 8723,
    "sha256": "cb41e48c894508e0c9d31df97be294826c9c4a169fea5f5b08ecc70416f58f90",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/character_rotation.py",
    "length": 30681,
    "sha256": "600b54e59e4a121800aef6d9703956f06ca3083ba64f08960123b78e7bdd1bc4",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/character_rotation.py.orig",
    "length": 28939,
    "sha256": "11d240e81e46565b620bb56f3a6c63db251511de22b513cf268e4f087e78a370",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/character_strategy.py",
    "length": 82646,
    "sha256": "87598925016a4783ef9051eb0b3da729dba05b91dec8c6bfb0e4ead5d2178b70",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/client.py",
    "length": 8878,
    "sha256": "c068e664bf19b60285747b8a13b1a3ffcc1590b040008335c70c7d4b9885b291",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/compact_knowledge.py",
    "length": 48911,
    "sha256": "8090231f958f6f1691d00dd72a17d0d42174217ce5f69ef70cbed2376dd2a256",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/config.json",
    "length": 2361,
    "sha256": "a1ec341e3150e462ae4afb6d9838f5e70197feecbbf8ea7477bb950552e47fa8",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/dashboard_launcher.py",
    "length": 6700,
    "sha256": "b283846760adabd0bbbb8f856fc31bbbbec62ab9d0dacf024efeccfac0eb4942",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/decision_trace.py",
    "length": 14572,
    "sha256": "8ecf3c4e0dcaff53768b005567ebe462b9833e7fb7f487582b03c34004febcf4",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/floor_stats.py",
    "length": 66483,
    "sha256": "14f73731b357028b8fd30a925806f5cad07edccf6e2b06a14adae650760c9bac",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/knowledge.py",
    "length": 148515,
    "sha256": "8aa2accce19b6a9bd6c910720d1e9684f0aca1d38b8e2823d568e5385f2d2062",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/lifecycle.py",
    "length": 13193,
    "sha256": "5b9b266ae18917b925bf0a64bb21d9c5392e953ca3085c72a728ea0a071c88aa",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/live_dashboard.py",
    "length": 14359,
    "sha256": "284a673df81c5562d488ef2600e727f0872542e55baf51af305890329880a15b",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/llm_review.py",
    "length": 474010,
    "sha256": "4c9e4abaa83a8ac50cb962bbb9ffe7d807653395f2592d0fe0e2dc1a115aa77b",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/manual_control.py",
    "length": 12066,
    "sha256": "91163fa34d1ad8636590394c9ce7df8811238283c192d5e79d38dc51ba63b2f3",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/native_knowledge.py",
    "length": 29546,
    "sha256": "d081d888d05405b6605423ee9de2bd0a788cfa49ef15b9f093d5754594c3e445",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/policy.py",
    "length": 463416,
    "sha256": "8df2179ce8145d9892750d41bc7a76f31a9ad41fc72b7fec77a127643d76ab89",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/reflect.py",
    "length": 48496,
    "sha256": "3561f71e95342e33eade8e197f6d53735834fd40fe5baf72ad09e32918c3843c",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/review_runners.py",
    "length": 25498,
    "sha256": "a6562121da5663e9db8d12ff23b90552fda2f2770e2953dc004706a0ff2f66e6",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/review_viewer.py",
    "length": 84371,
    "sha256": "775a7a407f3decd819bade4db432578c79e76873f7d19f115058644f86205100",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/runner.py",
    "length": 38948,
    "sha256": "b157e626a9f254d65c6ea380aa8aa9bb816906605602451a1bb5e144bf5e5d76",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/runtime_paths.py",
    "length": 2061,
    "sha256": "e4abf44d8bd3f6fa6f586ea0ccd490cbcb4b14dca13383946b988108f4707ec9",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/selfcheck.py",
    "length": 596373,
    "sha256": "1cc0f691926c59fc86dbf4355d75e4d62e5169ef7d33a9931a3478306c854a5d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/brain/window_layers.py",
    "length": 10726,
    "sha256": "43a1a402f91ade0ceb69f709cf89bf0804ccdb577d86abee0ebb901e7a6ce036",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_agent_profile_rotation_integration.py",
    "length": 20909,
    "sha256": "58c44629d36dc423bfe9a9b0c0f925b8f7b61ffcb76c4ac3324de3cc9d79e584",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_character_profiles.py",
    "length": 4399,
    "sha256": "80e65fa07a3179323563fada5cd36909b2ee8b828d65d11f7227f7775bf9eb4b",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_character_rotation.py",
    "length": 21602,
    "sha256": "d44b2e26ce1e0dc863bf99d1e6216767c492792315c249b458d9a2ab2a125860",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_character_strategy.py",
    "length": 71733,
    "sha256": "23c312012d7e51ec1786befea861a21504bd582dbbb438af21255341f62a1e1a",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_llm_profile_isolation.py",
    "length": 20823,
    "sha256": "006617a0a943cdabe70aabcf1129a009ab7fa37cf8436369588625ae6107e3dd",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_manual_control.py",
    "length": 22100,
    "sha256": "cde1b2bc3438ed7b42747799b845b97a4b827179d2de5b461a3a0f9b8bf7b468",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_native_game_over_save_barrier.py",
    "length": 13833,
    "sha256": "dd841265b715510c7f8bd7c445b33d9a4b1b5b956e53c56b1b05b9acbfeb11b8",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_profile_floor_stats.py",
    "length": 24162,
    "sha256": "cf92a86e04c4806b0546a14617ba2636b8dd23efd64d69398fd43e3b880de00f",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/sts2-ascend/tests/test_review_health_marker.py",
    "length": 12498,
    "sha256": "3b8d4391194222f5233e190c886a4bad9f60c5ca7e4dd47c67f58fcd56a8ee09",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-014ab6a54f8d7b748121d291.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-0643ea3a32c69c8916ff8e92.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-071ff6cffef748a4e947d9fe.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-2969461f3cadcd0d9b413718.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-30e8b7f3b7d44ddad678d2b5.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-40edd9d2972c32ef67a8b10d.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-6a33d1726d97410c3c4f2f0b.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-72c921acd707aa43e5b70431.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-95baf61611518bfb2e64f180.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-b8d90378477fcfbfeac7e3c5.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-be2da659a3f0dbe264eaec4d.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-c8116dd9d30d408903cac268.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-cee8a1cc6de6ceb0bc28c0bd.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-e14befda89cffd4e09395337.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-eec4b511e93ac19bd5cbd18b.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/temp/sts2-ascend-policy-f2bc290aae9e242338e0dd24.lock",
    "length": 1,
    "sha256": "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/test-knowledge/brain.log",
    "length": 1538,
    "sha256": "9df94cf7d7a3bf16b0a064c4b70df8d70bbe224ee66912dadda121775c3ff4b1",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Basics/ClosedDomainMapping.cs",
    "length": 1328,
    "sha256": "c3ab51a0b2fcf318beb48775fa6e3af021f77c93af9e97a95cdfba0c26be0965",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Basics/ClosedDomainMapping.cs.uid",
    "length": 19,
    "sha256": "1a8c855649a41ed1eb78a8e461ea5a196d022ab135f2c47961d5389dcf067d81",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Basics/LuminousProjection.cs",
    "length": 1568,
    "sha256": "d7029da3cc7dae38728f24c51a13e26edda80e6182b22a291b471ce3db62f3a6",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Basics/LuminousProjection.cs.uid",
    "length": 20,
    "sha256": "e45a44b8db7f98bbbd7b97db9895b365552276a363bfe9e7951486fd2a3912b5",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Basics/VivhiteTransformation.cs",
    "length": 1688,
    "sha256": "b180d34bcd204a5420da15f56f604648f16930e2415d9f06f50bfc88e6a13451",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Basics/VivhiteTransformation.cs.uid",
    "length": 20,
    "sha256": "0a095d6aa8a8670a665c4b39d2d3d807014e1ea189144bf88cf3346f548f9522",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/Chiaroscuro.cs",
    "length": 1492,
    "sha256": "885202e28833c49a6b087e5fa7affaa65457c1dde94832fd94af6ccdf7ab14f5",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/Chiaroscuro.cs.uid",
    "length": 20,
    "sha256": "2dc74634d0c2edb7b5ed8567246b7f82558b4d1c82649534036aafbfbd83b47c",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ChromaticCard.cs",
    "length": 6772,
    "sha256": "74bae562bec1868bfb62f3118d0aff1a892b556f8c2f9c6e65ae09823044aa05",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ChromaticCard.cs.uid",
    "length": 20,
    "sha256": "8723486cfd57fcd563ed172a57e353d4b533fe97c1efd8652c5efb4844f09515",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ChromaticDrainMechanics.cs",
    "length": 5119,
    "sha256": "b615c963d8a138cd988ee23a210cc0062d6d03e8be35779256bf0a468d8935d7",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ChromaticDrainMechanics.cs.uid",
    "length": 20,
    "sha256": "6db9d222cb24c8bb5b2ab139fb9e1b6d1af7354d803b86c125d140ca36452d5b",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ChromaticPowers.cs",
    "length": 3652,
    "sha256": "faf9f194c748d367b2644aac414aac7d7243a34746c304516072d60782d79fd6",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ChromaticPowers.cs.uid",
    "length": 20,
    "sha256": "440c984e4bd70d159b7d9fa67474cb0eddacfb25bfe97a980e8dafd4b514de88",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ChromaticTransition.cs",
    "length": 1343,
    "sha256": "c7482fb34a0c031b9a1d0d15e8edcc9e532be5d6dd55cc7422f8ecaa83228a6e",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ChromaticTransition.cs.uid",
    "length": 20,
    "sha256": "ceb07f5788df013231929ce4e7866c479c3cc0018c0abe7df9ca69c996ace2b4",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ColorConservation.cs",
    "length": 1068,
    "sha256": "e17c4cef9aa1b5d0c4765714755eced09dbc5839ffd42630f94b03c1b43232e0",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ColorConservation.cs.uid",
    "length": 20,
    "sha256": "71f939d2085d9e1f2beceaa239e87bd5a600ddb31810b82e672f04806b1509ed",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ComplementaryAfterimage.cs",
    "length": 1330,
    "sha256": "775c593da08c2854c51f673456b0705f48d916e8db0e3cae16e444784c3b758e",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/ComplementaryAfterimage.cs.uid",
    "length": 20,
    "sha256": "6b347ce87f20d5113640357549da07e07a0e345ca90f53716d6a710d63d19d80",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/CompositeColorField.cs",
    "length": 1827,
    "sha256": "4c0060a2d3a609897ff28db55ee68ee48a253d1774cf76f8e1c4a3a76dc8c857",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/CompositeColorField.cs.uid",
    "length": 19,
    "sha256": "2bc82d337c9bd3748da8d9e3c3f86b0a4bf5776aff95de31cc870e6e4dd1cf3d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/CompositeColorWheel.cs",
    "length": 1258,
    "sha256": "836efb6e3608994293ea831d5eb7bed071f64c5cd32f901e67c37281372c7945",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/CompositeColorWheel.cs.uid",
    "length": 20,
    "sha256": "fb542c46b294be1ea3628e385b29391ad788b0cde7903a40089a61d3f5a9fab1",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/CrimsonArea.cs",
    "length": 1243,
    "sha256": "5a1a6cf6dc87ee1c9906444a06329c43300628c1903086e90e8fe044ae10f0df",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/CrimsonArea.cs.uid",
    "length": 20,
    "sha256": "028b9c44bd8f790707d187acf287413542c9cf62d07fdb29c249a49d16e8eae8",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/CrimsonConservationLaw.cs",
    "length": 1540,
    "sha256": "6cd0944790c744809ee2ecf7b89f25d42961ea5be267cc82d6ce45283654277f",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/CrimsonConservationLaw.cs.uid",
    "length": 20,
    "sha256": "4cd6eb62ecb3b269f830203aae5c39f1da0e23589713e1699dbd74d9b1e91e37",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/DefiniteCrimsonIntegral.cs",
    "length": 1268,
    "sha256": "3572b817fe1dd77294e807f096584931e887cea4d5cd2673cd56904b1a2ce0b0",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/DefiniteCrimsonIntegral.cs.uid",
    "length": 20,
    "sha256": "7113a22d6e681fae700216d9f30199d67bbe70bade011d213b92f34f964555ce",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/DifferentialSampling.cs",
    "length": 1262,
    "sha256": "9da7713fd7441dff4aa4ea103a52074a63a66855c284934eca48ebb4b27ff3e9",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/DifferentialSampling.cs.uid",
    "length": 20,
    "sha256": "41f55ee2db30e796171fcdb2844ea8d809a30b4f8a2dfe0d11d2aa16ebb82b2b",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/GoldenComposition.cs",
    "length": 1259,
    "sha256": "0f460c2c0eb47115e81275f22a5a0feb85c8b43f237613b387563c22c568ac06",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/GoldenComposition.cs.uid",
    "length": 20,
    "sha256": "13de6995fed0a3948ffa07fcf50bc4c7888034d46206eb6af8cf537fc7dd763a",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/InfiniteCanvas.cs",
    "length": 1534,
    "sha256": "7386a12cee90791f1c5c1af32d3820d3b41b43a4e5e61823f6ebc2a063e1eced",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/InfiniteCanvas.cs.uid",
    "length": 20,
    "sha256": "f85e8b3b91c05842c11b0894651ad8ceb3bc31d70a86fb7c820a88e79827cce3",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/NegativeSpace.cs",
    "length": 1674,
    "sha256": "c5c7f8b52f8b336351cf139d067e7852c1a968a2ca4e986bce103723e6fb377f",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/NegativeSpace.cs.uid",
    "length": 20,
    "sha256": "9ce676307876dc89e5f3403f29ca0b7f09407db1f33e260bc51070be988a260d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/PerfectSynthesis.cs",
    "length": 1275,
    "sha256": "baffbf1c1076125587719e72d038ec065a33e41a80cb5d54026f20fea8ebbf87",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/PerfectSynthesis.cs.uid",
    "length": 20,
    "sha256": "bec18c5650451e10026806a3da243514ed7c899ac7f0400f4f1a729d426e1fac",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/RiemannStarArray.cs",
    "length": 1514,
    "sha256": "40719987c5ee9d24d20ee4cda0d5649633c06ff7df1ea949de4791e09d60be84",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/RiemannStarArray.cs.uid",
    "length": 19,
    "sha256": "e9ad9839217e77f188d11d14f58080c614206eb3f28cf2b2a4017c2dbf1d44c2",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/SpectralIntegral.cs",
    "length": 1217,
    "sha256": "71b1c4d1aa15e7824d525603a4196f0f9bcde8668a3c8728c44802171d001b62",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/SpectralIntegral.cs.uid",
    "length": 20,
    "sha256": "eb997cabf306e512db797f46390ef8d4fc72ffd46c826a10af493545e8d59b33",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/TrichromaticWaltz.cs",
    "length": 1257,
    "sha256": "e0972d85089dd7126cdc1ac8d68b162e5700c591e030a4a0b31f6347861f2438",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Chromatic/TrichromaticWaltz.cs.uid",
    "length": 20,
    "sha256": "6d2b261a00c9cd833b713294a8a872f1121a0b8cbae71cdcd9e5a35efedb1b1b",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Common/VivhiteCard.cs",
    "length": 1161,
    "sha256": "10c6b943cda2b67fb824e09fbf99d8240413b4bda9883e888e5e4a9560782b79",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Common/VivhiteCard.cs.uid",
    "length": 20,
    "sha256": "99683721b46494189986f69842adb52226aedc8a3b0f9bb99b42e5a9c88cb148",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Common/VivhiteCardRules.cs",
    "length": 3049,
    "sha256": "2a04465ee1edc4888c6503ed7f3567fa377ba8b9e7ee8452efc70ca2b761e846",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Common/VivhiteCardRules.cs.uid",
    "length": 19,
    "sha256": "193a60f4ff39fb3b976cf1e887f40ed34561fc89530b78e53aeb2bdae6af4785",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Common/VivhiteKeywords.cs",
    "length": 1684,
    "sha256": "3936a25320f9826598ba0cba0820c02ec234290a7ce7fb76fa2e17c7c7d572de",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Common/VivhiteKeywords.cs.uid",
    "length": 20,
    "sha256": "35056c1d75b0d1955949775bcf01db23a991ec1bdeb82a65e583cae97a046623",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Common/VivhiteLifeCalculationCard.cs",
    "length": 2859,
    "sha256": "b1f92f82e2547848637c694e660033358c5e82cfca35710f011f3a24656d932f",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Common/VivhiteLifeCalculationCard.cs.uid",
    "length": 20,
    "sha256": "1186e30fba94c4b3f52f3b6bfcd5c957adcea1bdf208ad119ff7ca612b5fae75",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationCard.cs",
    "length": 3412,
    "sha256": "2ad1f26ab8337e685c8a7e6ac4019b73173387900dcde42e0ceec43c6b24fc4e",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationCard.cs.uid",
    "length": 20,
    "sha256": "0330856ddbde17bd6e6a942d9e6d6c0463d3a0759f1f69ef9ff4087db679d386",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationCommonCards.cs",
    "length": 6837,
    "sha256": "5579e40a917681dce3b5077b38afa7690d9c831c6fe1742f5e125363615c83be",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationCommonCards.cs.uid",
    "length": 20,
    "sha256": "fc08eaccee850100cee393242da740c5281c7dc91b834c6b3e07af432b174474",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationPowers.cs",
    "length": 4365,
    "sha256": "ab66b5ea975f13c6cf42a2c2dc44c3ece6e5b2549d0d0b1b61e01a67d07a3b0e",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationPowers.cs.uid",
    "length": 20,
    "sha256": "cfe34631d16adc05b0bb3efc3f3e3e437849c3123b515ce1b8b127ab6aa9d160",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationRareCards.cs",
    "length": 4515,
    "sha256": "7ead96a3223a8866daec7d30b35bfa865b9e76740141f15ab55d7a4f6da0f006",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationRareCards.cs.uid",
    "length": 20,
    "sha256": "8c7734627ec5c2ba7ecb402eef3f3d5a012b9947d58af27685c84ca809c56a73",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationUncommonCards.cs",
    "length": 8091,
    "sha256": "3c934101b3746355765a6cc9b62b4d5485718da76b7a785fbc2016a3b5a18730",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Conservation/ConservationUncommonCards.cs.uid",
    "length": 20,
    "sha256": "cd1c7a856d3cf72ab8f13b43bb3f447dbbca557a3deff10d57051d9745504f03",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/AstralMeasure.cs",
    "length": 1858,
    "sha256": "c342560f9949c1db28acdf0c00778d893778fc5e07893584917f48a7e47fcd25",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/AstralMeasure.cs.uid",
    "length": 20,
    "sha256": "a0ee0aecdef069ede98810a9d68d6204f3ac5369dc258caa18e410a78ef751a5",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/ChromaticLimit.cs",
    "length": 2238,
    "sha256": "0c5cc28a643d66b0b6ae211d916b043f67a45285a2dee7c8603f92b5c0b3b239",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/ChromaticLimit.cs.uid",
    "length": 20,
    "sha256": "bedf1f588318d9850fe459dc6659ccd67349c5f71c6fbe2e0216c223b7e435f3",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/ChromaticSequence.cs",
    "length": 2329,
    "sha256": "33d68b3dd07822eba0fe76f64ad42b264941dce6456f732857fbd870c2c41136",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/ChromaticSequence.cs.uid",
    "length": 20,
    "sha256": "5c0dcb1386e0cb688f8182f2464ab55b91506f8a636533f712c45c8db14d734f",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/ConservedRecurrence.cs",
    "length": 2154,
    "sha256": "c635731192a30a988f773ab88d9b46370d7df02f18cba5a01bb773a1fb9930e4",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/ConservedRecurrence.cs.uid",
    "length": 19,
    "sha256": "93d3bbd931b5d62a56d56be4f75366774545ff21faaf8cfbfff9b6191dd6fc3c",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/GoldenRatio.cs",
    "length": 1833,
    "sha256": "280105bfcba7aad9bd016a6da5bc5ec9cbc2821ffc57afbef5e7acba8474fb33",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/GoldenRatio.cs.uid",
    "length": 19,
    "sha256": "9014bcc15c1819ca0d224a9a806acc2f517d6fb39bf6be561bcbc570be97579b",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/UnifiedFieldTheory.cs",
    "length": 1736,
    "sha256": "0a9a41fd9870fbd4d7c825f60554c9ee3a3a5947bdaa617c2d780e5056f55859",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/UnifiedFieldTheory.cs.uid",
    "length": 19,
    "sha256": "7c18cab1f0a6d8a0e15a5dff30e0cc038116bf207e27017e2bdcad1de542b0a2",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/UnifiedFieldTheoryPowers.cs",
    "length": 3191,
    "sha256": "e8d8d1009207c682d59acdef14684a038cf1841460d9001028c20dee27671cbe",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/UnifiedFieldTheoryPowers.cs.uid",
    "length": 20,
    "sha256": "44e3e63faf48d1c34154a1f88369ff49653406e0d68c819133d41ae1aec81554",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/VivhitesCrimsonTransformationRitual.cs",
    "length": 2150,
    "sha256": "94c39207e30f88952bb7b66737898e70f4df8c18554f60f99928c0a56f9f601a",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/VivhitesCrimsonTransformationRitual.cs.uid",
    "length": 20,
    "sha256": "80ce75da7bab1cd3d2cc42bd28fafa816fb215fc1c7d5c4e5fa023068bcee49c",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/VivhitesCrimsonTransformationRitualPowers.cs",
    "length": 8775,
    "sha256": "f7dfd46669a005dde955422c69d51634aa656b8cd5088e33b295ac156ee580ba",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Hybrid/VivhitesCrimsonTransformationRitualPowers.cs.uid",
    "length": 20,
    "sha256": "c0319e810148d147f680f498c645a2a8f04911a21993c465ab2805b09823be96",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionCard.cs",
    "length": 2721,
    "sha256": "5be55cb29a0066e0c529b46eb0fa17e249fe289fb35de96cf93e14155f4c1cb0",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionCard.cs.uid",
    "length": 20,
    "sha256": "5249e9979c104c1942d27acb3b6aed1e81b77a3ea46cdcf89be5dda1728f55d9",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionCommonCards.cs",
    "length": 6100,
    "sha256": "87858de436a81865a7dfab5ba32918c04e2201237380bf1d78b5fa81c3dadb66",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionCommonCards.cs.uid",
    "length": 20,
    "sha256": "4d82d17bb84479bf13539133755b1ee838fdccfffc2fa3dfad8775492599388c",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionPowers.cs",
    "length": 7201,
    "sha256": "46e2c7338cb1540009548686ec68aa60118b2bd879feb154c01c0de76fc9a137",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionPowers.cs.uid",
    "length": 20,
    "sha256": "7bbbdb70af2ba4b8b13dcb1ea36ee7fd04699fe9ed8dcf223e98281aff49757f",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionRareCards.cs",
    "length": 4310,
    "sha256": "4a3a710b7778cfa7f276c5a421b7ec9deb06f112381c7decac1c6053c15fda9e",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionRareCards.cs.uid",
    "length": 20,
    "sha256": "bc4dd3c08c57ad685d6eb654cd0bd4edbd66b2e1034392acccd0c2264c1dc42d",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionUncommonCards.cs",
    "length": 9463,
    "sha256": "fb44c45b414cee5fbd6d297fd99801baa274822feda915a51ecec1302b09c716",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/Recursion/RecursionUncommonCards.cs.uid",
    "length": 20,
    "sha256": "6f7586becff4d36f9b2117dbb7aabc110e0c268833aca5e865e40903817f2f36",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/VivhiteDefend.cs.uid",
    "length": 20,
    "sha256": "3e5ab08bab6293883bffb531738ed136749db6c63318dce2bce10cfb7e48aa14",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/final-profile-audit-work-20260831-132137396/Vivhite/VivhiteCode/Cards/VivhiteStrike.cs.uid",
    "length": 19,
    "sha256": "203502f4fc02ea0933350a4f9909c5bc835c868fcc4310cbc258ac71a37b57c6",
    "category": "redundant-profile-audit-copy"
  },
  {
    "path": ".tmp/gameover-cross-process-recovery.index",
    "length": 855731,
    "sha256": "3103545e31e74a29aeaf170ace7903c7a0118d1bc50130c8a5b0b832e32f531a",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/gameover-cross-process-recovery.patch",
    "length": 14866,
    "sha256": "855ea27178d1964b4d3647f4ede077af80161c5b3f98af9dd1b5826a92d71b06",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/inspect-game-save-path/inspect-game-save-path.csproj",
    "length": 237,
    "sha256": "933bfd93fb4668ecf73c60797396a2f0e200a7b82512e75de5ba7bdd5be269de",
    "category": "diagnostic-source"
  },
  {
    "path": ".tmp/inspect-game-save-path/Program.cs",
    "length": 9040,
    "sha256": "2dd4f24f3c8fde6010ee64bd3f88532f755ea6f5b656a41eb696b6b070681a65",
    "category": "diagnostic-source"
  },
  {
    "path": ".tmp/llm-profile-isolation-task.patch",
    "length": 12260,
    "sha256": "3beab8564b90016b232c8e50e2321347727a79ef5e70c195680767e2aa1d1ec4",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/llm-profile-isolation.index",
    "length": 855314,
    "sha256": "0d7446ffc363143daa552e86e3b462d83280d41c8475e0c59a3babfb754bffe4",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/localization-20260831.index",
    "length": 855731,
    "sha256": "d5bf39c4b784722edbdb2c73bb873885d543f93db916692e668e77320916f8e2",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/native-barrier-phase-test-fix.patch",
    "length": 4500,
    "sha256": "2e4764092fb233b3aa445f13d618084103c54b3fd0a63e6e3f43421552b2853c",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/native-gameover-doc-20260831.index",
    "length": 855731,
    "sha256": "38c582787c83a1f6d6d74377e04836ae6f869fda5d8ed722f3aaaed836dc0911",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/native-gameover-docs-v2.patch",
    "length": 22641,
    "sha256": "c34931bb632fa81276ce8817019d6174fdb211f876c447bdf4b1bc9297c354e8",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/passive-doc-20260831.index",
    "length": 855731,
    "sha256": "8bdc03d286cdee954de05cc516d25c419635ddbaf1fc0bd2c048a8bc4c510e1b",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/pck-gate-92-localization-v3.patch",
    "length": 61681,
    "sha256": "80b82cf8773622c85e53046208bdcbec548b66cdab771f52e32a032f36c94210",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/pck-gate-doc-v2-isolated-e74a93e9993e410386affd1c1ccf9875/docs/2026-08-31-\u767d\u7eeePCK\u56db\u5c42\u53ea\u8bfb\u95e8\u7981.md",
    "length": 3950,
    "sha256": "642dd93700d07e711fefc7a8043adffe86859aaf98a88faad872a2710eb69e6b",
    "category": "committed-isolated-doc"
  },
  {
    "path": ".tmp/pck-gate-doc-v2-isolated-e74a93e9993e410386affd1c1ccf9875/review.index",
    "length": 878475,
    "sha256": "2ab097af8c66cafb82ba5f84fadd03f7edf77af13cb6325e2eb6dc22f86d1919",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/pck-gate-doc-v2-private-34727f3f54914171afa0254b5b947df6.index",
    "length": 878475,
    "sha256": "2ab097af8c66cafb82ba5f84fadd03f7edf77af13cb6325e2eb6dc22f86d1919",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/pck-gate-doc-v2-private-lf-d3f475ba707948e29c025c2ccab0188a.index",
    "length": 878475,
    "sha256": "c404bad8f474959ea77ea576cf282354d1d25477531b9bca5169ad860400473e",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/pck-gate-doc-v2.patch",
    "length": 6798,
    "sha256": "6141e850165aa75eeca35a7eae06077c11635a77e33159e51ae1d5f071673047",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/pck-gate-v3-a778059a.index",
    "length": 878475,
    "sha256": "9bf6e429576a65fde90fb370594f6e0c506fc6f00629b7eeb374f7b88fcfe91d",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/pck-gate.index",
    "length": 855731,
    "sha256": "d5039cf38e5994c0e4a47128c2e83c5087c6b26f9d30dd01b36257c914000f33",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/profile-in-progress-gameover-fix.patch",
    "length": 19976,
    "sha256": "a8353e25b0309ef62318e1406880bb8554ccad681ca9b8d5367772fedd1e00ba",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/restore-cross-process-recovery-tests.patch",
    "length": 8219,
    "sha256": "9f29d1c220deecb41fe5e0c044249bda809b83721e1cd693de261835e879d1e8",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/retired-runtime-placeholder-cleanup.v2.patch",
    "length": 949958,
    "sha256": "2c7d8aaad1af0c1e0f76d0e96610b5035dc8daebc1a8b2304c7f4164cd7fcbab",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/retired-runtime-placeholder-work-v1/.gitignore",
    "length": 553,
    "sha256": "893c81f5539910b127f422dca67ee03e61e9ec1c725d888e2e3c86cc7dff0bc2",
    "category": "retired-temp-file"
  },
  {
    "path": ".tmp/runtime-art-archive-13b75d39.index",
    "length": 878475,
    "sha256": "160ef99b9cab33095a77cf0da0ce8490d848144bb9cd1363a661b4f7df36520e",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/runtime-art-living-docs.v5.patch",
    "length": 30318,
    "sha256": "fe6807d85bdecd5823c3e7e954465f3f341731e07a9bd95e0f3b92687fbba16c",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/sts2-decompiler/Program.cs",
    "length": 1721,
    "sha256": "dd53f2d8c9fda5998b9e20301cb306efbe68ed962f3dff3731f2b50840a8a187",
    "category": "diagnostic-source"
  },
  {
    "path": ".tmp/sts2-decompiler/sts2-decompiler.csproj",
    "length": 470,
    "sha256": "85cada70d73dd8aaea86d9269666bf3a560bbee63decc1ea00db4f8159c34633",
    "category": "diagnostic-source"
  },
  {
    "path": ".tmp/sts2-readme-final-89cfe7e8.index",
    "length": 856203,
    "sha256": "2a43a3b2529ce574ecd76deb145627a4d2a9811095c66521e58c27319856ed08",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/sts2-readme.index",
    "length": 855314,
    "sha256": "8ae2c7e0f145d17b49faaa0c3b17816e5421684e955eb599ef6a8b02bc72a755",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/trail-patch-validation-aac2d01bbb254bb3b1b567247539e7f6.index",
    "length": 855314,
    "sha256": "9d28ebb6a8f8ab03258535ac366b1d1bf716192dbaed9301caabf0c7ce69bd69",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/ui-icon-check.log",
    "length": 78,
    "sha256": "a6d3f05458d9fbcdb2cc6b767f081b9e52f4bf3450bd183ddd1b20ee22986221",
    "category": "ui-icon-log"
  },
  {
    "path": ".tmp/ui-icon-run.log",
    "length": 152,
    "sha256": "e1bcf30aafe1dcac25bbeccf02929325a36d304476c36a8e40bcf2570e2da893",
    "category": "ui-icon-log"
  },
  {
    "path": ".tmp/vivhite-passive-design-doc.patch",
    "length": 2607,
    "sha256": "c7ea802fe8f1d30a333b9c2dd6424c46ad35cdfd6bac86b42ae3504b07ffe19a",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/vivhite-readmes-final-c30bd594.index",
    "length": 878475,
    "sha256": "e1871ff97c217f392354552cd4747737d03dad623ad4d7d88b6b10106b93fc86",
    "category": "redundant-private-index"
  },
  {
    "path": ".tmp/vivhite-readmes-final.v2.patch",
    "length": 20532,
    "sha256": "c350c061e87a94882cbc942e6d51d96b7cb2a9a317a96676e07348fd3d13c163",
    "category": "applied-or-origin-patch"
  },
  {
    "path": ".tmp/vivhite-transition-wiring.patch",
    "length": 3068,
    "sha256": "f843505f7ed3fad10c43aa7219778216d2a7dcc1dde3caecb08de5cedec17ba8",
    "category": "applied-or-origin-patch"
  }
]
'@

function Test-ContainedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Container
    )

    $containerPrefix = $Container.TrimEnd([char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)) +
        [IO.Path]::DirectorySeparatorChar
    return $Candidate.StartsWith($containerPrefix, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NotReparsePoint {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Label is a reparse point; refusing cleanup: $Path"
    }
}

function Get-ManifestAbsolutePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or
        -not $RelativePath.StartsWith('.tmp/', [StringComparison]::Ordinal) -or
        [IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath.IndexOf([char]92) -ge 0) {
        throw "Unsafe manifest path syntax: $RelativePath"
    }

    $segments = @($RelativePath.Split('/'))
    if ($segments.Count -lt 2 -or $segments[0] -ne '.tmp') {
        throw "Manifest path is not a file below .tmp: $RelativePath"
    }
    foreach ($segment in $segments) {
        if ([string]::IsNullOrWhiteSpace($segment) -or $segment -eq '.' -or $segment -eq '..') {
            throw "Manifest path contains an unsafe segment: $RelativePath"
        }
    }

    $platformRelative = $RelativePath.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $candidate = [IO.Path]::GetFullPath((Join-Path $script:RepoRoot $platformRelative))
    if (-not (Test-ContainedPath -Candidate $candidate -Container $script:TmpRoot)) {
        throw "Resolved manifest path escaped repository .tmp: $RelativePath -> $candidate"
    }

    $cursor = $script:RepoRoot
    foreach ($segment in $segments) {
        $cursor = Join-Path $cursor $segment
        if (Test-Path -LiteralPath $cursor) {
            Assert-NotReparsePoint -Path $cursor -Label "Manifest path component"
        }
    }

    return $candidate
}

function Assert-StackStopped {
    $blockers = New-Object 'System.Collections.Generic.List[string]'
    $sessionFile = Join-Path $script:RuntimeDir 'session.json'
    if (Test-Path -LiteralPath $sessionFile) {
        [void]$blockers.Add("active session metadata: $sessionFile")
    }

    foreach ($pidFile in @(Get-ChildItem -LiteralPath $script:RuntimeDir -Filter '*.pid' -File -Force -ErrorAction SilentlyContinue)) {
        [void]$blockers.Add("stack PID record: $($pidFile.FullName)")
    }

    $markerNames = @(
        'viewer.lock',
        'voice_quipper.lock',
        'voice_speaker.lock',
        'voice_nano.lock',
        'voice_quip_speaking.flag',
        'voice_clone_busy.flag',
        'review_active.flag'
    )
    foreach ($name in $markerNames) {
        $marker = Join-Path $script:KnowledgeDir $name
        if (Test-Path -LiteralPath $marker) {
            [void]$blockers.Add("live component marker: $marker")
        }
    }

    $componentPaths = @(
        (Join-Path $script:StackRoot 'brain\runner.py'),
        (Join-Path $script:StackRoot 'brain\review_viewer.py'),
        (Join-Path $script:StackRoot 'brain\llm_review.py'),
        (Join-Path $script:StackRoot 'tts\quipper.py'),
        (Join-Path $script:StackRoot 'tts\edge_speaker.py'),
        (Join-Path $script:StackRoot 'tts\nano_speaker.py'),
        (Join-Path $script:StackRoot 'tts\speaker.py'),
        (Join-Path $script:StackRoot 'tts\speak_once.py')
    )
    $reviewWorkRoot = Join-Path $script:StackRoot 'knowledge\code_backups\review_work'

    try {
        $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    } catch {
        throw "Cannot prove the stack is stopped because Win32_Process inspection failed: $($_.Exception.Message)"
    }

    foreach ($process in $processes) {
        $name = [string]$process.Name
        $commandLine = [string]$process.CommandLine
        if ([string]::IsNullOrWhiteSpace($commandLine)) {
            continue
        }

        $matched = $false
        if ($name -match '^(python(?:w|\d+(?:\.\d+)*)?|py|uv)\.exe$') {
            foreach ($componentPath in $componentPaths) {
                if ($commandLine.IndexOf($componentPath, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    $matched = $true
                    break
                }
            }
            if (-not $matched -and
                $commandLine -match '(?i)(^|\s)-m\s+brain(?:\s|$)') {
                $matched = $true
            }
            if (-not $matched -and
                $commandLine -match '(?i)(^|[\s"''])brain[\\/]runner\.py(?=$|[\s"''])' -and
                $commandLine -notmatch '(?i)(^|\s)-m\s+py_compile(?:\s|$)') {
                $matched = $true
            }
            if (-not $matched -and
                $commandLine.IndexOf($reviewWorkRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $matched = $true
            }
        }

        if (-not $matched -and $name -match '^(opencode|codex)(\.exe)?$' -and
            ($commandLine.IndexOf($reviewWorkRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
             ($commandLine -match '(?i)--auto' -and
              $commandLine.IndexOf('sts2-ascend', [StringComparison]::OrdinalIgnoreCase) -ge 0))) {
            $matched = $true
        }

        if ($matched) {
            [void]$blockers.Add("live stack process pid $($process.ProcessId): $name")
        }
    }

    if ($blockers.Count -gt 0) {
        $details = ($blockers | Sort-Object -Unique) -join [Environment]::NewLine
        throw "Stack-stopped precondition failed. Run the unified Stop-Agent.ps1 entry point and retry. Blockers:$([Environment]::NewLine)$details"
    }
}

function Get-SnapshotState {
    param([Parameter(Mandatory = $true)][object]$Entry)

    $absolutePath = Get-ManifestAbsolutePath -RelativePath ([string]$Entry.Path)
    if (-not (Test-Path -LiteralPath $absolutePath)) {
        return [pscustomobject]@{
            Status = 'Missing'
            Path = [string]$Entry.Path
            AbsolutePath = $absolutePath
            Reason = 'file does not exist'
        }
    }
    if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
        return [pscustomobject]@{
            Status = 'Changed'
            Path = [string]$Entry.Path
            AbsolutePath = $absolutePath
            Reason = 'snapshot file is no longer a regular file'
        }
    }

    $resolvedPath = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $absolutePath).ProviderPath)
    if (-not (Test-ContainedPath -Candidate $resolvedPath -Container $script:TmpRoot) -or
        -not $resolvedPath.Equals($absolutePath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved file path failed .tmp containment proof: $($Entry.Path) -> $resolvedPath"
    }

    Assert-NotReparsePoint -Path $resolvedPath -Label 'Snapshot file'
    $item = Get-Item -LiteralPath $resolvedPath -Force
    if ([long]$item.Length -ne [long]$Entry.Length) {
        return [pscustomobject]@{
            Status = 'Changed'
            Path = [string]$Entry.Path
            AbsolutePath = $resolvedPath
            Reason = "length changed: expected $($Entry.Length), found $($item.Length)"
        }
    }

    $actualHash = (Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne ([string]$Entry.Sha256).ToLowerInvariant()) {
        return [pscustomobject]@{
            Status = 'Changed'
            Path = [string]$Entry.Path
            AbsolutePath = $resolvedPath
            Reason = "SHA-256 changed: expected $($Entry.Sha256), found $actualHash"
        }
    }

    return [pscustomobject]@{
        Status = 'Ready'
        Path = [string]$Entry.Path
        AbsolutePath = $resolvedPath
        Length = [long]$Entry.Length
        Sha256 = ([string]$Entry.Sha256).ToLowerInvariant()
    }
}

$RepoRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath)
$TmpRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath (Join-Path $RepoRoot '.tmp')).ProviderPath)
$StackRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot 'sts2-ascend'))
$RuntimeDir = Join-Path $StackRoot '.runtime'
$KnowledgeDir = Join-Path $StackRoot 'knowledge'

if (-not (Test-Path -LiteralPath $TmpRoot -PathType Container)) {
    throw "Repository .tmp directory does not exist: $TmpRoot"
}
Assert-NotReparsePoint -Path $TmpRoot -Label 'Repository .tmp root'

$decodedManifest = $ManifestJson | ConvertFrom-Json
$manifest = New-Object 'System.Collections.Generic.List[object]'
foreach ($decodedEntry in $decodedManifest) {
    [void]$manifest.Add($decodedEntry)
}
if ($manifest.Count -ne $ExpectedFileCount) {
    throw "Embedded manifest count mismatch: expected $ExpectedFileCount, found $($manifest.Count)"
}

$normalizedManifest = New-Object 'System.Collections.Generic.List[object]'
$seenPaths = @{}
$manifestBytes = [long]0
foreach ($rawEntry in $manifest) {
    $path = [string]$rawEntry.path
    $length = [long]$rawEntry.length
    $hash = ([string]$rawEntry.sha256).ToLowerInvariant()
    if ($length -lt 0 -or $hash -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid snapshot metadata for path: $path"
    }
    if ($seenPaths.ContainsKey($path)) {
        throw "Duplicate manifest path: $path"
    }
    $seenPaths[$path] = $true
    [void](Get-ManifestAbsolutePath -RelativePath $path)
    [void]$normalizedManifest.Add([pscustomobject]@{
        Path = $path
        Length = $length
        Sha256 = $hash
        Category = [string]$rawEntry.category
    })
    $manifestBytes += $length
}
if ($manifestBytes -ne $ExpectedBytes) {
    throw "Embedded manifest byte total mismatch: expected $ExpectedBytes, found $manifestBytes"
}

if (-not (Test-Path -LiteralPath $RuntimeDir -PathType Container)) {
    throw "Cannot prove the stack is stopped because its runtime directory is absent: $RuntimeDir"
}
$lifecycleLockPath = Join-Path $RuntimeDir 'lifecycle.lock'
if (-not (Test-Path -LiteralPath $lifecycleLockPath -PathType Leaf)) {
    throw "Cannot serialize against Start-Agent/Stop-Agent because lifecycle.lock is absent: $lifecycleLockPath"
}

$lifecycleLock = $null
try {
    try {
        $lifecycleLock = [IO.File]::Open(
            $lifecycleLockPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    } catch {
        throw "A Start-Agent/Stop-Agent operation is in progress; cleanup is refused."
    }

    Assert-StackStopped

    if ($Apply -and $ConfirmationPhrase -cne $RequiredConfirmationPhrase) {
        throw "Apply mode requires -ConfirmationPhrase $RequiredConfirmationPhrase"
    }

    $ready = New-Object 'System.Collections.Generic.List[object]'
    $missing = New-Object 'System.Collections.Generic.List[object]'
    $changed = New-Object 'System.Collections.Generic.List[object]'

    foreach ($entry in $normalizedManifest) {
        $state = Get-SnapshotState -Entry $entry
        switch ($state.Status) {
            'Ready' { [void]$ready.Add($state) }
            'Missing' { [void]$missing.Add($state) }
            'Changed' { [void]$changed.Add($state) }
            default { throw "Unknown snapshot state for $($entry.Path): $($state.Status)" }
        }
    }

    $readyBytes = [long](($ready | Measure-Object -Property Length -Sum).Sum)
    Write-Host "Snapshot: $SnapshotId"
    Write-Host "Classification snapshot: $ClassificationSnapshotAt"
    Write-Host "Hash manifest frozen: $HashManifestFrozenAt"
    Write-Host "Manifest: $ExpectedFileCount files, $ExpectedBytes bytes"
    Write-Host "Preflight: ready=$($ready.Count) ($readyBytes bytes), missing=$($missing.Count), changed=$($changed.Count)"

    foreach ($item in $missing) {
        Write-Warning "SKIP_MISSING $($item.Path): $($item.Reason)"
    }
    foreach ($item in $changed) {
        Write-Warning "SKIP_CHANGED $($item.Path): $($item.Reason)"
    }

    if (-not $Apply) {
        Write-Host 'Preview only. No files were removed.'
        Write-Host "To apply after reviewing this output, rerun with -Apply -ConfirmationPhrase $RequiredConfirmationPhrase"
        return
    }

    $removedCount = 0
    $removedBytes = [long]0
    $secondCheckMissing = 0
    $secondCheckChanged = 0
    $notApproved = 0
    $failures = New-Object 'System.Collections.Generic.List[string]'

    foreach ($entry in $ready) {
        $latest = Get-SnapshotState -Entry $entry
        if ($latest.Status -eq 'Missing') {
            $secondCheckMissing += 1
            Write-Warning "SKIP_MISSING $($entry.Path): changed after preflight"
            continue
        }
        if ($latest.Status -ne 'Ready') {
            $secondCheckChanged += 1
            Write-Warning "SKIP_CHANGED $($entry.Path): $($latest.Reason)"
            continue
        }

        if (-not $PSCmdlet.ShouldProcess($latest.AbsolutePath, "remove immutable safe-.tmp snapshot file")) {
            $notApproved += 1
            continue
        }

        try {
            Remove-Item -LiteralPath $latest.AbsolutePath -Force -ErrorAction Stop
            $removedCount += 1
            $removedBytes += [long]$latest.Length
            Write-Host "REMOVED $($latest.Path)"
        } catch {
            [void]$failures.Add("$($latest.Path): $($_.Exception.Message)")
            Write-Warning "REMOVE_FAILED $($latest.Path): $($_.Exception.Message)"
        }
    }

    Write-Host "Cleanup summary: removed=$removedCount, bytes=$removedBytes, preflight_missing=$($missing.Count), preflight_changed=$($changed.Count), second_check_missing=$secondCheckMissing, second_check_changed=$secondCheckChanged, not_approved=$notApproved, failures=$($failures.Count)"
    Write-Host 'Directories were not removed; empty directories, if any, were intentionally left in place.'

    if ($failures.Count -gt 0) {
        throw "One or more individual file removals failed. See REMOVE_FAILED lines above."
    }
} finally {
    if ($null -ne $lifecycleLock) {
        $lifecycleLock.Dispose()
    }
}
