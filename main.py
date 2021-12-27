import asyncio
import logging
import xml.etree.ElementTree as ET
from argparse import ArgumentParser
from functools import reduce
from os import getenv
from pathlib import Path
from textwrap import shorten
from time import perf_counter
from typing import Generator, List, Tuple

import aiofiles
import aiofiles.ospath

logging.basicConfig(level=getenv('LOGGING_LEVEL', logging.INFO))


async def is_valid_folder_path(folder_path: str) -> bool:
    if not await aiofiles.ospath.exists(folder_path):
        logging.error(f'{folder_path} does not exist')
        return False

    if not await aiofiles.ospath.isdir(folder_path):
        logging.error(f'{folder_path} is not a directory')
        return False

    return True


async def get_invoices_from_folder(folder_path: str, extension: str = 'xml') -> Generator[Path, None, None]:

    if not await is_valid_folder_path(folder_path):
        return []

    return Path(folder_path).glob(f'*.{extension}')


async def load_invoices(invoices: Generator[Path, None, None], is_own: bool) -> List[ET.Element]:

    async def xml_from_file(invoice: Path) -> ET.Element:
        async with aiofiles.open(invoice.resolve(), 'r', encoding='utf-8') as file:
            file_as_str = await file.read()
            root_node = ET.fromstring(file_as_str)
            return root_node if is_own else ET.fromstring(root_node.find('comprobante').text.lstrip(' \n'))

    if not invoices:
        logging.warning('No invoices to process, exiting')
        return []

    logging.info('Reading invoices ...')

    return await asyncio.gather(*[xml_from_file(invoice) for invoice in invoices])


def process_invoices(invoices: List[ET.Element]) -> Tuple[list, dict]:

    def get_node(node: ET.Element, structure: tuple, depth: int = 0) -> ET.Element:
        if depth == len(structure):
            return node
        return get_node(node.find(structure[depth]), structure, depth+1)

    def format_tax_node(name_node: ET.Element, tax_node: ET.Element) -> tuple:
        tax_value = float(tax_node.find('valor').text)*100
        return name_node.text, float(tax_node.find('baseImponible').text)*100, tax_value

    def add_taxes(values: dict, tax_node: tuple) -> dict:
        new_values = {**values}
        _, taxable_value, tax_value = tax_node
        new_values.update(
            {
                'total_with_taxes': values.get('total_with_taxes', 0) + (taxable_value if tax_value != 0 else 0),
                'total_no_taxes': values.get('total_no_taxes', 0) + (taxable_value if tax_value == 0 else 0),
                'tax': values.get('tax', 0) + tax_value
            }
        )
        return new_values

    def get_values_from_invoice(invoice) -> tuple:
        tax_parent_nodes = ('infoFactura', 'totalConImpuestos')
        name_parent_nodes = ('infoTributaria', 'razonSocial')
        name_node = get_node(invoice, name_parent_nodes)
        tax_node = get_node(invoice, tax_parent_nodes)
        return tuple(format_tax_node(name_node, node) for node in tax_node.findall('totalImpuesto'))

    if not invoices:
        return [], {}

    logging.info(f'Processing {len(invoices)} invoices')
    overall_taxes = []
    final_values = {'total_with_taxes': 0, 'total_no_taxes': 0, 'tax': 0}
    for invoice in invoices:
        overall_taxes.extend(get_values_from_invoice(invoice))

    return overall_taxes, reduce(add_taxes, overall_taxes, final_values)


def print_values(overal_taxes: list, results: dict):
    if not overal_taxes:
        return

    min_name_len = len(min(overal_taxes, key=lambda value: len(value[0]))[0])
    max_len = min_name_len+30
    for name, taxable_value, tax in overal_taxes:
        short_name = shorten(name, width=max_len)
        print(f'{short_name} {str(taxable_value/100).rjust(max_len-len(short_name)+10)} $ {tax/100:10} $')
    print('-'*(max_len+26))
    for key, value in results.items():
        print(f'{key:4} => $ {value/100:4}')


def get_args() -> str:
    parser = ArgumentParser()
    parser.add_argument("-p", "--path", help="Path to your invoice folder", type=str, default='./invoices')
    parser.add_argument("-o", "--own", help="Toggle formatting when the invoices are yours", type=bool, default=False)
    parsed_args = parser.parse_args()
    return parsed_args.path, parsed_args.own


async def main():

    input_folder, own = get_args()

    invoice_paths = await get_invoices_from_folder(input_folder)
    invoices = await load_invoices(invoice_paths, own)
    result_values = process_invoices(invoices)

    print_values(*result_values)


if __name__ == '__main__':
    start = perf_counter()
    asyncio.run(main())
    end = perf_counter()
    logging.info(f'Took {end-start:.2f}s to process your request')
