import pandas as pd
import numpy as np
import os
import sys
import csv
import time
from .linkperformance_fieldconfig import (
    DISTRICT_ID_FIELD,
    FREE_SPEED_FIELD,
    FROM_NODE_ID_FIELD,
    LEGACY_LENGTH_MILE_FIELD,
    LENGTH_FIELD,
    LINK_ID_FIELD,
    LINK_FILENAME,
    LINK_PERFORMANCE_FILENAME,
    LINK_TYPE_FIELD,
    PAIR_FIELD,
    PERSON_VOLUME_FIELD,
    SPEED_FIELD,
    TAZ_FIELD,
    TO_NODE_ID_FIELD,
    VEHICLE_VOLUME_FIELD,
    VOLUME_FIELD,
    GEOMETRY_FIELD,
    district_id_name_mapping,
)
from .preprocessor import resolve_period_file


LEGACY_PERSON_VOLUME_FIELD = "person_volume"
LEGACY_SPEED_FIELD = "speed"


def _ensure_comparison_aliases(link_performance_df):
    if VEHICLE_VOLUME_FIELD not in link_performance_df.columns and VOLUME_FIELD in link_performance_df.columns:
        link_performance_df[VEHICLE_VOLUME_FIELD] = link_performance_df[VOLUME_FIELD]
    if LEGACY_PERSON_VOLUME_FIELD not in link_performance_df.columns and PERSON_VOLUME_FIELD in link_performance_df.columns:
        link_performance_df[LEGACY_PERSON_VOLUME_FIELD] = link_performance_df[PERSON_VOLUME_FIELD]
    if SPEED_FIELD not in link_performance_df.columns and LEGACY_SPEED_FIELD in link_performance_df.columns:
        link_performance_df[SPEED_FIELD] = link_performance_df[LEGACY_SPEED_FIELD]
    return link_performance_df


def diff_stats(nb_link_per, nb_link, bd_link_per, bd_link, time_period, period_length, parent_dir):
    nb_link_per = _ensure_comparison_aliases(nb_link_per.copy())
    bd_link_per = _ensure_comparison_aliases(bd_link_per.copy())

    for link_df in (bd_link, nb_link):
        if PAIR_FIELD not in link_df.columns:
            link_df[PAIR_FIELD] = list(zip(link_df[FROM_NODE_ID_FIELD], link_df[TO_NODE_ID_FIELD]))
        if LEGACY_LENGTH_MILE_FIELD not in link_df.columns and LENGTH_FIELD in link_df.columns:
            link_df[LEGACY_LENGTH_MILE_FIELD] = link_df[LENGTH_FIELD]

    # district_id_dict = {8:'District of Columbia',21:'Montgomery',22:"Prince George's",3:'Arlington',
    #                   1:'Alexandria',9:'Fairfax',10:'Fairfax City',11:'Falls Church',18:'Loudoun',
    #                    23:'Prince William',19:'Manassas',20:'Manassas Park',13:'Frederick',15:'Howard',
    #                    2:'Anne Arundel',6:'Charles',5:'Carroll',4:'Calvert',25:"St. Mary's",17:'King George',
    #                    14:'Fredericksburg',26:'Stafford',24:'Spotsylvania',12:'Fauquier',7:'Clarke',16:'Jefferson'}

    # district_id_dict = {'Arlington': 2, 'Alexandria': 1, 'Fairfax': 3, 'Fairfax City': 4, 'Falls Church': 5,
    # 'Loudoun': 6, 'Prince William': 9, 'Manassas': 7, 'Manassas Park':8}

    district_id_dict = district_id_name_mapping

    bd_link_per[PAIR_FIELD] = list(zip(bd_link_per[FROM_NODE_ID_FIELD], bd_link_per[TO_NODE_ID_FIELD]))
    # old_vdf_code = vdf_code / 100; FT = int(old_vdf_code % 10)
    old_vdf_code_bd = bd_link_per[LINK_TYPE_FIELD] / 100
    link_type_ft_bd = (old_vdf_code_bd % 10).astype(int)
    bd_link_per['FT'] = link_type_ft_bd

    bd_attrs = bd_link[[PAIR_FIELD, TAZ_FIELD, DISTRICT_ID_FIELD, LEGACY_LENGTH_MILE_FIELD, FREE_SPEED_FIELD]].drop_duplicates(subset=PAIR_FIELD)
    bd_link_per = bd_link_per.merge(bd_attrs, on=PAIR_FIELD, how='left')
    bd_link_per[[TAZ_FIELD, DISTRICT_ID_FIELD, LEGACY_LENGTH_MILE_FIELD, FREE_SPEED_FIELD]] = bd_link_per[
        [TAZ_FIELD, DISTRICT_ID_FIELD, LEGACY_LENGTH_MILE_FIELD, FREE_SPEED_FIELD]
    ].fillna(-1)
    bd_link_per['FFTT'] = bd_link_per[LEGACY_LENGTH_MILE_FIELD] / bd_link_per[FREE_SPEED_FIELD]
    # unit in hours
    bd_link_per['TT'] = bd_link_per[LEGACY_LENGTH_MILE_FIELD] / bd_link_per[SPEED_FIELD]
    # unit in hours
    bd_link_per['delay'] = bd_link_per['TT'] - bd_link_per['FFTT']
    bd_link_per['person_delay'] = bd_link_per[LEGACY_PERSON_VOLUME_FIELD] * bd_link_per.delay

    nb_link_per[PAIR_FIELD] = list(zip(nb_link_per[FROM_NODE_ID_FIELD], nb_link_per[TO_NODE_ID_FIELD]))

    # old_vdf_code = vdf_code / 100; FT = int(old_vdf_code % 10)
    old_vdf_code = nb_link_per[LINK_TYPE_FIELD] / 100
    link_type_ft = (old_vdf_code % 10).astype(int)
    nb_link_per['FT'] = link_type_ft

    nb_attrs = nb_link[[PAIR_FIELD, LEGACY_LENGTH_MILE_FIELD, FREE_SPEED_FIELD]].drop_duplicates(subset=PAIR_FIELD)
    nb_link_per = nb_link_per.merge(nb_attrs, on=PAIR_FIELD, how='left')
    nb_link_per[[LEGACY_LENGTH_MILE_FIELD, FREE_SPEED_FIELD]] = nb_link_per[[LEGACY_LENGTH_MILE_FIELD, FREE_SPEED_FIELD]].fillna(-1)

    nb_link_per['FFTT'] = nb_link_per[LEGACY_LENGTH_MILE_FIELD] / nb_link_per[FREE_SPEED_FIELD]
    # unit in hours
    nb_link_per['TT'] = nb_link_per[LEGACY_LENGTH_MILE_FIELD] / nb_link_per[SPEED_FIELD]
    # unit in hours
    nb_link_per['delay'] = nb_link_per['TT'] - nb_link_per['FFTT']
    nb_link_per['person_delay'] = nb_link_per[LEGACY_PERSON_VOLUME_FIELD] * nb_link_per.delay

    bd_df = bd_link_per[(bd_link_per[TAZ_FIELD] > 1404) & (bd_link_per[TAZ_FIELD] < 2820) & (bd_link_per['FT'] > 0)]

    dif_bd = bd_df[
        [LINK_ID_FIELD, FROM_NODE_ID_FIELD, TO_NODE_ID_FIELD, PAIR_FIELD, VEHICLE_VOLUME_FIELD, SPEED_FIELD, 'person_delay', GEOMETRY_FIELD, 'FT', TAZ_FIELD,
         DISTRICT_ID_FIELD]].copy()

    # dif_bd['JUR_name'] = dif_bd.apply(lambda x: district_id_dict.setdefault(x.district_id, -1), axis=1)
    dif_bd['JUR_name'] = dif_bd[DISTRICT_ID_FIELD].map(district_id_dict)
    # Replace missing values (district IDs not in the dictionary) with -1
    dif_bd['JUR_name'].fillna(-1, inplace=True)

    dif_bd = dif_bd.rename(columns=lambda s: s + '_bd')

    nb_lookup = nb_link_per[[PAIR_FIELD, LINK_ID_FIELD, FROM_NODE_ID_FIELD, TO_NODE_ID_FIELD, VEHICLE_VOLUME_FIELD, SPEED_FIELD, 'person_delay']].rename(
        columns=lambda col: f"{col}_nb" if col != PAIR_FIELD else "pair_bd"
    )
    dif_bd = dif_bd.merge(nb_lookup, on='pair_bd', how='left').fillna({
        f'{LINK_ID_FIELD}_nb': -1,
        f'{FROM_NODE_ID_FIELD}_nb': -1,
        f'{TO_NODE_ID_FIELD}_nb': -1,
        f'{VEHICLE_VOLUME_FIELD}_nb': -1,
        f'{SPEED_FIELD}_nb': -1,
        'person_delay_nb': -1,
    })
    # dif_bd['mild_congestion_duration_nb'] = np.minimum(dif_bd.apply(lambda x: P_nb_dict.setdefault(x.pair_bd, -1),
    # axis=1),period_length) dif_bd['sever_congestion_duration_nb'] = np.minimum(dif_bd.apply(lambda x:
    # sever_P_nb_dict.setdefault(x.pair_bd, -1), axis=1),period_length) dif_bd['JUR_name'] = dif_bd.apply(lambda x:
    # district_id_dict.setdefault(x.district_id_bd, -1), axis=1) diff = dif_bd.set_index('pair').join(
    # dif_nb.set_index('pair'), how='right', lsuffix='_bd', rsuffix='_nb', sort=False)

    dif_bd['diff_vehicle_volume'] = dif_bd[f'{VEHICLE_VOLUME_FIELD}_bd'] - dif_bd[f'{VEHICLE_VOLUME_FIELD}_nb']
    dif_bd['diff_speed_mph'] = dif_bd[f'{SPEED_FIELD}_bd'] - dif_bd[f'{SPEED_FIELD}_nb']
    dif_bd['diff_person_delay'] = dif_bd['person_delay_bd'] - dif_bd['person_delay_nb']
    # dif_bd['diff_mild_congestion_duration']=dif_bd['mild_congestion_duration_bd']-dif_bd['mild_congestion_duration_nb']
    # dif_bd['diff_sever_congestion_duration']=dif_bd['sever_congestion_duration_bd']-dif_bd['sever_congestion_duration_nb']

    dif_bd.loc[dif_bd[f'{SPEED_FIELD}_nb'] == -1, "diff_speed_mph"] = -1
    dif_bd.loc[dif_bd[f'{VEHICLE_VOLUME_FIELD}_nb'] == -1, "diff_vehicle_volume"] = -1
    dif_bd.loc[dif_bd[f'{VEHICLE_VOLUME_FIELD}_nb'] == -1, "diff_person_delay"] = -1
    # dif_bd.loc[dif_bd.mild_congestion_duration_nb == -1 , "diff_mild_congestion_duration"] = -1
    # dif_bd.loc[dif_bd.sever_congestion_duration_nb == -1 , "diff_sever_congestion_duration"] = -1

    # dif_bd=dif_bd.drop(['link_type'],axis=1)
    dif_bd = dif_bd.drop(['pair_bd'], axis=1)
    # dif_bd=dif_bd.drop(['district_id_bd'],axis=1)

    dif_bd.to_csv(os.path.join(parent_dir, f'diff_{time_period}.csv'), index=False)


def district_based_diff(net_dir_bd, net_dir_nb, parent_dir):
    case_bd = net_dir_bd.split('\\')[-1]
    case_nb = net_dir_nb.split('\\')[-1]

    net_list = []
    net_list = [net_dir_bd, net_dir_nb]

    for net_dir in net_list:
        case = case_bd if net_dir == net_dir_bd else case_nb
        output = os.path.join(net_dir, f'link_performance_{case}.csv')
        if not os.path.exists(output):
            link_perf_net_am = pd.read_csv(os.path.join(net_dir, 'link_performance_am.csv'))
            link_perf_net_md = pd.read_csv(os.path.join(net_dir, 'link_performance_md.csv'))
            link_perf_net_pm = pd.read_csv(os.path.join(net_dir, 'link_performance_pm.csv'))
            link_perf_net_nt = pd.read_csv(os.path.join(net_dir, 'link_performance_nt.csv'))

            link_perf_net = link_perf_net_am[
                ['link_id', 'from_node_id', 'to_node_id', 'speed', 'volume', 'person_volume',
                 'geometry', 'link_type']].copy()

            link_perf_net['speed'] = (3 * link_perf_net_am['speed'] + 6 * link_perf_net_md['speed'] +
                                      4 * link_perf_net_pm['speed'] + 11 * link_perf_net_nt['speed']) / 24

            link_perf_net['volume'] = (link_perf_net_am['volume'] + link_perf_net_md['volume'] +
                                       link_perf_net_pm['volume'] + link_perf_net_nt['volume'])

            link_perf_net['person_volume'] = (link_perf_net_am['person_volume'] + link_perf_net_md['person_volume'] +
                                              link_perf_net_pm['person_volume'] + link_perf_net_nt['person_volume'])

            link_perf_net.to_csv(os.path.join(net_dir, f'link_performance_{case}.csv'), index=False)

            print(
                'link performance statistics has been generated for the whole day and saved in the following directory: \n %s' % (
                    net_dir))

    link_net_bd = pd.read_csv(os.path.join(net_dir_bd, 'link.csv'))
    link_net_nb = pd.read_csv(os.path.join(net_dir_nb, 'link.csv'))
    # node_net = pd.read_csv(os.path.join(net_dir, 'node.csv'))

    # pair_taz_dict = dict(zip(link_net.pair, link_net.TAZ))
    # pair_jur_dict = dict(zip(link_net.pair, link_net.JUR))
    pair_jurname_dict_bd = dict(zip(link_net_bd.pair, link_net_bd.JUR_NAME))
    pair_district_dict_bd = dict(zip(link_net_bd.pair, link_net_bd.district_id))
    pair_district_dict_nb = dict(zip(link_net_nb.pair, link_net_nb.district_id))

    length_dict_bd = dict(zip(link_net_bd.pair, link_net_bd.length_in_mile))
    length_dict_nb = dict(zip(link_net_nb.pair, link_net_nb.length_in_mile))

    free_speed_dict_bd = dict(zip(link_net_bd.pair, link_net_bd.free_speed))
    free_speed_dict_nb = dict(zip(link_net_nb.pair, link_net_nb.free_speed))

    district_id_dict = {'Arlington': 2,
                        'Alexandria': 1,
                        'Fairfax': 3,
                        'Fairfax City': 4,
                        'Falls Church': 5,
                        'Loudoun': 6,
                        'Prince William': 9,
                        'Manassas': 7,
                        'Manassas Park': 8
                        }

    agent_type = ['apv', 'com', 'hov2', 'hov3', 'sov', 'trk']

    link_perf_net_bd = pd.read_csv(os.path.join(net_dir_bd, f'link_performance_{case_bd}.csv'))
    link_perf_net_bd['pair'] = link_perf_net_bd['from_node_id'].astype(str) + '->' + link_perf_net_bd[
        'to_node_id'].astype(str)
    link_perf_net_bd['district_id'] = link_perf_net_bd.apply(lambda x: pair_district_dict_bd.setdefault(x.pair, -1),
                                                             axis=1)
    link_perf_net_bd['Jur_name'] = link_perf_net_bd.apply(lambda x: pair_jurname_dict_bd.setdefault(x.pair, -1), axis=1)

    link_perf_net_nb = pd.read_csv(os.path.join(net_dir_nb, f'link_performance_{case_nb}.csv'))
    link_perf_net_nb['pair'] = link_perf_net_nb['from_node_id'].astype(str) + '->' + link_perf_net_nb[
        'to_node_id'].astype(str)
    link_perf_net_nb['district_id'] = link_perf_net_nb.apply(lambda x: pair_district_dict_nb.setdefault(x.pair, -1),
                                                             axis=1)

    for district_name, district_id in district_id_dict.items():

        link_perf_jur_net_bd = link_perf_net_bd[link_perf_net_bd['district_id'] == district_id].copy()
        link_perf_jur_net_nb = link_perf_net_nb[link_perf_net_nb['district_id'] == district_id].copy()

        # df1 = df[(df.a != -1) & (df.b != -1)]

        # print('link performance file filtered by %s = %s' % (jur_group_id,jur_id))
        # ft_dict = dict(zip(link_perf_jur_net_bd.pair, link_perf_jur_net_bd.link_type%10))
        link_perf_jur_net_bd['FT'] = link_perf_jur_net_bd.link_type % 10

        link_perf_jur_net_bd['length_in_mile'] = link_perf_jur_net_bd.apply(
            lambda x: length_dict_bd.setdefault(x.pair, -1), axis=1)
        link_perf_jur_net_bd['free_speed'] = link_perf_jur_net_bd.apply(
            lambda x: free_speed_dict_bd.setdefault(x.pair, -1), axis=1)
        link_perf_jur_net_bd['FFTT'] = link_perf_jur_net_bd['length_in_mile'] / link_perf_jur_net_bd['free_speed']
        # unit in hours
        link_perf_jur_net_bd['TT'] = link_perf_jur_net_bd['length_in_mile'] / link_perf_jur_net_bd['speed']
        # unit in hours
        link_perf_jur_net_bd['delay'] = link_perf_jur_net_bd['TT'] - link_perf_jur_net_bd['FFTT']
        link_perf_jur_net_bd['person_delay'] = link_perf_jur_net_bd.person_volume * link_perf_jur_net_bd.delay
        link_perf_jur_net_bd['person_hour'] = link_perf_jur_net_bd.person_volume * link_perf_jur_net_bd.TT
        link_perf_jur_net_bd['person_mile'] = link_perf_jur_net_bd.person_volume * link_perf_jur_net_bd.length_in_mile

        dif_bd = link_perf_jur_net_bd[['link_id', 'from_node_id', 'to_node_id', 'pair', 'Jur_name', 'volume',
                                       'speed', 'person_delay', 'person_mile', 'geometry', 'FT']].copy()

        # diff.insert (1, "FT", '')
        # dif_bd['FT'] = dif_bd.apply(lambda x: ft_dict.setdefault(x.link_id, -1), axis=1)

        link_perf_jur_net_nb['length_in_mile'] = link_perf_jur_net_nb.apply(
            lambda x: length_dict_nb.setdefault(x.pair, -1), axis=1)
        link_perf_jur_net_nb['free_speed'] = link_perf_jur_net_nb.apply(
            lambda x: free_speed_dict_nb.setdefault(x.pair, -1), axis=1)
        link_perf_jur_net_nb['FFTT'] = link_perf_jur_net_nb['length_in_mile'] / link_perf_jur_net_nb['free_speed']
        # unit in hours
        link_perf_jur_net_nb['TT'] = link_perf_jur_net_nb['length_in_mile'] / link_perf_jur_net_nb['speed']
        # unit in hours
        link_perf_jur_net_nb['delay'] = link_perf_jur_net_nb['TT'] - link_perf_jur_net_nb['FFTT']
        link_perf_jur_net_nb['person_delay'] = link_perf_jur_net_nb.person_volume * link_perf_jur_net_nb.delay
        # link_perf_jur_net_nb['person_hour'] = link_perf_jur_net_nb.person_volume * link_perf_jur_net_nb.TT
        link_perf_jur_net_nb['person_mile'] = link_perf_jur_net_nb.person_volume * link_perf_jur_net_nb.length_in_mile

        dif_nb = link_perf_jur_net_nb[['link_id', 'from_node_id', 'to_node_id', 'pair', 'volume',
                                       'speed', 'person_delay', 'person_mile']].copy()
        dif_bd = dif_bd.rename(columns=lambda s: s + '_' + case_bd)

        link_id_nb_dict = dict(zip(dif_nb.pair, dif_nb.link_id))
        from_nb_dict = dict(zip(dif_nb.pair, dif_nb.from_node_id))
        to_nb_dict = dict(zip(dif_nb.pair, dif_nb.to_node_id))
        volume_nb_dict = dict(zip(dif_nb.pair, dif_nb.volume))
        speed_nb_dict = dict(zip(dif_nb.pair, dif_nb.speed))
        phd_nb_dict = dict(zip(dif_nb.pair, dif_nb.person_delay))
        pmt_nb_dict = dict(zip(dif_nb.pair, dif_nb.person_mile))

        dif_bd[f'link_id_{case_nb}'] = dif_bd.apply(lambda x: link_id_nb_dict.setdefault(x[f'pair_{case_bd}'], -1),
                                                    axis=1)
        dif_bd[f'from_node_id_{case_nb}'] = dif_bd.apply(lambda x: from_nb_dict.setdefault(x[f'pair_{case_bd}'], -1),
                                                         axis=1)
        dif_bd[f'to_node_id_{case_nb}'] = dif_bd.apply(lambda x: to_nb_dict.setdefault(x[f'pair_{case_bd}'], -1),
                                                       axis=1)
        dif_bd[f'volume_{case_nb}'] = dif_bd.apply(lambda x: volume_nb_dict.setdefault(x[f'pair_{case_bd}'], -1),
                                                   axis=1)
        dif_bd[f'speed_{case_nb}'] = dif_bd.apply(lambda x: speed_nb_dict.setdefault(x[f'pair_{case_bd}'], -1), axis=1)
        dif_bd[f'person_delay_{case_nb}'] = dif_bd.apply(lambda x: phd_nb_dict.setdefault(x[f'pair_{case_bd}'], -1),
                                                         axis=1)
        dif_bd[f'person_mile_{case_nb}'] = dif_bd.apply(lambda x: pmt_nb_dict.setdefault(x[f'pair_{case_bd}'], -1),
                                                        axis=1)

        # diff = dif_bd.set_index('pair').join(dif_nb.set_index('pair'), how='right', lsuffix='_bd', rsuffix='_nb',
        # sort=False)

        dif_bd['diff_volume'] = dif_bd[f'volume_{case_bd}'] - dif_bd[f'volume_{case_nb}']
        dif_bd['diff_speed'] = dif_bd[f'speed_{case_bd}'] - dif_bd[f'speed_{case_nb}']
        dif_bd['diff_PHD'] = dif_bd[f'person_delay_{case_bd}'] - dif_bd[f'person_delay_{case_nb}']
        dif_bd['diff_PMT'] = dif_bd[f'person_mile_{case_bd}'] - dif_bd[f'person_mile_{case_nb}']

        dif_bd.loc[dif_bd[f'speed_{case_nb}'] == -1, "diff_speed"] = -1
        dif_bd.loc[dif_bd[f'volume_{case_nb}'] == -1, "diff_volume"] = -1
        dif_bd.loc[dif_bd[f'person_delay_{case_nb}'] == -1, "diff_PHD"] = -1
        dif_bd.loc[dif_bd[f'person_mile_{case_nb}'] == -1, "diff_PMT"] = -1

        dif_bd = dif_bd.drop([f'pair_{case_bd}'], axis=1)

        output_folder_name = f'diff_{case_bd}_{case_nb}'

        output_path = os.path.join(parent_dir, output_folder_name)

        if not os.path.exists(output_path):
            os.makedirs(output_path)

        dif_bd.to_csv(os.path.join(output_path, f'diff_{district_name}.csv'), index=False)


def get_period_diff(time_periods, period_length_dict, parent_dir, nb_net, bd_net):
    bd_net_dir = os.path.join(parent_dir, f'{bd_net}')
    nb_net_dir = os.path.join(parent_dir, f'{nb_net}')

    print('NB network = %s' % (nb_net))
    print('BD network = %s' % (bd_net))

    for time_period in time_periods:
        period_length = period_length_dict.get(time_period)

        bd_link = pd.read_csv(resolve_period_file(bd_net_dir, time_period, LINK_FILENAME))
        nb_link = pd.read_csv(resolve_period_file(nb_net_dir, time_period, LINK_FILENAME))

        nb_link_perf = pd.read_csv(resolve_period_file(nb_net_dir, time_period, LINK_PERFORMANCE_FILENAME))
        bd_link_perf = pd.read_csv(resolve_period_file(bd_net_dir, time_period, LINK_PERFORMANCE_FILENAME))

        diff_stats(nb_link_perf, nb_link, bd_link_perf, bd_link, time_period, period_length, parent_dir)

        print('diff file for %s generated' % (time_period))


def creat_pair_net(net_list):
    organized_data = {}

    for item in net_list:
        name = item.rstrip('_BD').rstrip('_NB')
        if name not in organized_data:
            organized_data[name] = []

        if item.endswith('_BD'):
            organized_data[name].append(item)
        elif item.endswith('_NB'):
            organized_data[name].append(item)
        else:
            organized_data[name].append([item])

    final_list = [value if len(value) > 1 else value[0] for value in organized_data.values()]
    return final_list
